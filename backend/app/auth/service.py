"""Synchronous auth transactions, with a clock injectable by isolated tests."""
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from secrets import compare_digest, token_urlsafe
from uuid import UUID

from sqlalchemy import and_, delete, func, insert, or_, select, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError

from app.auth.models import AuthSession, RateLimit, User
from app.auth.security import hash_password, verify_password
from app.db import assert_project_database

COOKIE = "dra_session"
ORIGINS = frozenset({"http://127.0.0.1:5173", "http://127.0.0.1:8000"})
IDLE = timedelta(minutes=30)
ABSOLUTE = timedelta(hours=8)
PRE_SESSION = timedelta(minutes=10)


def utcnow():
    return datetime.now(timezone.utc)


class AuthError(Exception):
    def __init__(self, status=401, code="unauthenticated", message="Please log in.", retry_after=None):
        self.status, self.code, self.message = status, code, message
        self.retry_after = retry_after
        super().__init__(code)


def forbidden():
    return AuthError(403, "forbidden", "Request verification failed.")


@contextmanager
def transaction(engine, settings):
    try:
        with engine.begin() as connection:
            assert_project_database(connection, settings)
            yield connection
    except (SQLAlchemyError, RuntimeError):
        raise AuthError(503, "unavailable", "Service is temporarily unavailable.") from None


def digest(raw):
    if not isinstance(raw, str) or not 1 <= len(raw) <= 128 or not raw.isascii():
        return None
    return sha256(raw.encode("ascii")).digest()


@dataclass(frozen=True)
class Identity:
    token_digest: bytes = field(repr=False)
    user_id: UUID | None
    session_context: UUID
    expires_at: datetime
    csrf_token: str = field(repr=False)
    email: str | None = None


def find_session(connection, token_digest, clock, *, lock=False, touch=False):
    if token_digest is None:
        return None
    query = select(AuthSession.__table__).where(AuthSession.token_digest == token_digest)
    if lock:
        query = query.with_for_update()
    row = connection.execute(query).mappings().one_or_none()
    now = clock()  # Re-read after lock acquisition: queued writes cannot use stale time.
    if row is None or row["revoked_at"] is not None or row["expires_at"] <= now:
        return None
    if row["user_id"] is not None and row["last_seen_at"] + IDLE <= now:
        return None
    if touch:
        connection.execute(update(AuthSession).where(AuthSession.token_digest == token_digest).values(last_seen_at=now))
    email = connection.scalar(select(User.email).where(User.id == row["user_id"])) if row["user_id"] else None
    return Identity(token_digest, row["user_id"], row["session_context"], row["expires_at"], row["csrf_token"], email)


def require_session(connection, token_digest, clock, *, touch=True):
    identity = find_session(connection, token_digest, clock, lock=True)
    if identity is None or identity.user_id is None:
        raise AuthError()
    if touch:
        connection.execute(update(AuthSession).where(AuthSession.token_digest == token_digest).values(last_seen_at=clock()))
    return identity


def authenticate(engine, settings, raw, clock, *, touch=True):
    with transaction(engine, settings) as connection:
        return require_session(connection, digest(raw), clock, touch=touch)


def check_csrf(identity, value):
    if not isinstance(value, str) or not 1 <= len(value) <= 128 or not value.isascii():
        raise forbidden()
    if not compare_digest(identity.csrf_token, value):
        raise forbidden()


def checked_context(connection, raw, csrf, clock):
    identity = find_session(connection, digest(raw), clock, lock=True)
    if identity is None:
        raise forbidden()
    check_csrf(identity, csrf)
    return identity


def new_session(connection, user_id, now):
    raw, csrf = token_urlsafe(32), token_urlsafe(32)
    expires = now + (ABSOLUTE if user_id is not None else PRE_SESSION)
    row = connection.execute(insert(AuthSession).values(
        token_digest=digest(raw), user_id=user_id, csrf_token=csrf,
        created_at=now, last_seen_at=now, expires_at=expires,
    ).returning(AuthSession.session_context)).one()
    email = connection.scalar(select(User.email).where(User.id == user_id)) if user_id else None
    return raw, Identity(digest(raw), user_id, row.session_context, expires, csrf, email)


def bootstrap(engine, settings, raw, clock):
    with transaction(engine, settings) as connection:
        identity = find_session(connection, digest(raw), clock, lock=True, touch=True)
        if identity:
            return None, identity
        return new_session(connection, None, clock())


def throttle(engine, settings, budgets, clock):
    """Atomic saturating UPSERTs; commit attempts even when rejecting a request."""
    retry = 0
    with transaction(engine, settings) as connection:
        now = clock()
        for scope, key, maximum, seconds in budgets:
            start = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, timezone.utc)
            end = start + timedelta(seconds=seconds)
            stmt = pg_insert(RateLimit).values(scope=scope, key=key, window_start=start, attempts=1, expires_at=end)
            count = connection.scalar(stmt.on_conflict_do_update(
                index_elements=[RateLimit.scope, RateLimit.key, RateLimit.window_start],
                set_={"attempts": func.least(RateLimit.attempts + 1, maximum + 1)},
            ).returning(RateLimit.attempts))
            if count > maximum:
                retry = max(retry, max(1, int((end - now).total_seconds()) + 1))
    if retry:
        raise AuthError(429, "rate_limited", "Too many requests. Try again later.", retry)


def register(engine, settings, credentials, raw, csrf, clock):
    email, key = credentials.identity()
    encoded = hash_password(credentials.password)  # No row lock during hashing.
    with transaction(engine, settings) as connection:
        identity = checked_context(connection, raw, csrf, clock)
        if identity.user_id is not None:
            raise AuthError(400, "logout_required", "Log out before registering.")
        # Concurrent duplicates acknowledge identically; never overwrite a password.
        connection.execute(pg_insert(User).values(email=email, email_key=key, password_hash=encoded)
                           .on_conflict_do_nothing(index_elements=[User.email_key]))


def login(engine, settings, credentials, raw, csrf, clock):
    _, key = credentials.identity()
    with transaction(engine, settings) as connection:
        row = connection.execute(select(User.id, User.password_hash).where(User.email_key == key)).mappings().one_or_none()
    valid, updated = verify_password(credentials.password, row["password_hash"] if row else None)
    if not valid or row is None:
        raise AuthError(401, "invalid_credentials", "Email or password is incorrect.")
    with transaction(engine, settings) as connection:
        prior = checked_context(connection, raw, csrf, clock)
        now = clock()
        connection.execute(update(AuthSession).where(AuthSession.token_digest == prior.token_digest).values(revoked_at=now))
        if updated:
            connection.execute(update(User).where(User.id == row["id"]).values(password_hash=updated))
        return new_session(connection, row["id"], now)


def logout(engine, settings, raw, csrf, clock):
    with transaction(engine, settings) as connection:
        identity = find_session(connection, digest(raw), clock, lock=True)
        if identity:
            check_csrf(identity, csrf)
            connection.execute(update(AuthSession).where(AuthSession.token_digest == identity.token_digest).values(revoked_at=clock()))


def cleanup(engine, settings, clock, batch_size=500):
    """One bounded batch per table; skip locks held by live requests."""
    if not 1 <= batch_size <= 1000:
        raise ValueError("Batch size must be between 1 and 1000")
    with transaction(engine, settings) as connection:
        now = clock()
        expired = or_(AuthSession.revoked_at.is_not(None), AuthSession.expires_at <= now,
                      and_(AuthSession.user_id.is_not(None), AuthSession.last_seen_at <= now - IDLE))
        candidates = select(AuthSession.token_digest).where(expired).order_by(AuthSession.expires_at).limit(batch_size).with_for_update(skip_locked=True)
        sessions = connection.execute(delete(AuthSession).where(AuthSession.token_digest.in_(candidates))).rowcount
        rates = select(RateLimit.scope, RateLimit.key, RateLimit.window_start).where(
            RateLimit.expires_at <= now).order_by(RateLimit.expires_at).limit(batch_size).with_for_update(skip_locked=True)
        counters = connection.execute(delete(RateLimit).where(tuple_(RateLimit.scope, RateLimit.key, RateLimit.window_start).in_(rates))).rowcount
        return {"sessions": sessions, "rate_limits": counters}
