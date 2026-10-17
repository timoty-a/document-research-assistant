"""Synthetic HTTP/real PostgreSQL auth checks, exclusively in isolated schemas."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Event
from uuid import UUID, uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import event, func, insert, select, update
from sqlalchemy.exc import OperationalError
from starlette.formparsers import MultiPartParser

from app.auth import service
from app.auth.models import AuthSession, RateLimit, User
from app.auth.security import Credentials, hash_password, verify_password
from app.documents.models import Document

pytestmark = pytest.mark.database
ORIGIN = "http://127.0.0.1:8000"
PASSWORD = "Synthetic secure password 123!"


from auth_helpers import Browser, Clock


def count(database, model):
    with database.engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(model))


def test_registration_canonical_identity_duplicate_and_explicit_login(browsers):
    make, _, database = browsers
    a = make()
    a.bootstrap()
    first = a.post("/auth/register", json={"email": "  Student@EXAMPLE.com ", "password": PASSWORD})
    second = a.post("/auth/register", json={"email": "student@example.com", "password": "Different synthetic password"})
    assert first.status_code == second.status_code == 202
    assert first.json() == second.json()
    assert a.client.get("/auth/me").status_code == 401
    assert count(database, User) == 1
    with database.engine.connect() as connection:
        user = connection.execute(select(User.__table__)).mappings().one()
        assert user["email_key"] == "student@example.com" and user["email_verified_at"] is None
        assert user["password_hash"].startswith("$argon2id$v=19$m=65536,t=3,p=4$")
    assert a.login("STUDENT@example.com").status_code == 200
    assert a.post("/auth/register", json={"email": "other@example.com", "password": PASSWORD}).status_code == 400


def test_concurrent_registration_is_one_account_without_overwrite(browsers):
    make, _, database = browsers
    clients = [make(), make()]
    for browser in clients:
        browser.bootstrap()
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda b: b.post("/auth/register", json={"email": "race@example.com", "password": PASSWORD}), clients))
    assert [r.status_code for r in responses] == [202, 202]
    assert responses[0].json() == responses[1].json() and count(database, User) == 1


@pytest.mark.parametrize("payload", [
    {"email": "invalid", "password": PASSWORD},
    {"email": "x@example.com", "password": "short-secret"},
    {"email": "x@example.com", "password": "x" * 129},
    {"email": "x@example.com", "password": 123456789},
    {"email": "x@example.com", "password": PASSWORD, "owner_id": "forged"},
    {"email": "a" * 1025, "password": PASSWORD},
    {"email": "élève@example.com", "password": PASSWORD},
    {"email": "a@example.com", "password": "\ud800" * 15},
])
def test_credential_validation_never_echoes_inputs(browsers, payload, caplog):
    make, _, database = browsers
    a = make(); a.bootstrap()
    import json
    response = a.post("/auth/register", content=json.dumps(payload), headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert "input" not in response.json() and PASSWORD not in response.text + caplog.text
    assert count(database, User) == 0


def test_credential_media_body_limits_and_malformed_json(browsers):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    assert a.post("/auth/register", content="bad").status_code == 415
    assert a.post("/auth/register", content="{", headers={"Content-Type": "application/json"}).status_code == 422
    assert a.post("/auth/register", content=b"x" * 8193, headers={"Content-Type": "application/json", "Content-Length": "1"}).status_code == 413


def test_email_idna_and_password_preservation():
    credentials = Credentials(email="Student@bücher.de", password="  Synthetic password 123  ")
    assert credentials.identity() == ("Student@bücher.de", "student@xn--bcher-kva.de")
    encoded = hash_password(credentials.password)
    assert verify_password(credentials.password, encoded)[0]
    assert not verify_password(SecretStr("Synthetic password 123"), encoded)[0]


def test_wrong_unknown_login_have_same_error_and_keep_current_session(browsers):
    make, _, _ = browsers
    a = make(); a.account()
    cookie = a.client.cookies.get(service.COOKIE)
    wrong = a.login(password="Incorrect synthetic password")
    unknown = a.login("unknown@example.com")
    assert wrong.status_code == unknown.status_code == 401 and wrong.json() == unknown.json()
    assert a.client.cookies.get(service.COOKIE) == cookie
    assert a.client.get("/auth/me").status_code == 200


def test_rotation_revocation_cookies_context_and_restart(browsers):
    make, clock, database = browsers
    a = make(); a.bootstrap()
    pre_cookie, pre_csrf = a.client.cookies.get(service.COOKIE), a.csrf
    assert a.post("/auth/register", json={"email": "student@example.com", "password": PASSWORD}).status_code == 202
    response = a.login()
    auth_cookie = a.client.cookies.get(service.COOKIE)
    context = response.json()["session_context"]
    assert auth_cookie != pre_cookie and a.csrf != pre_csrf
    attributes = response.headers["set-cookie"].lower()
    assert "httponly" in attributes and "samesite=lax" in attributes and "path=/" in attributes
    assert "secure" not in attributes and "domain=" not in attributes
    assert "no-store" == response.headers["cache-control"]
    assert response.headers["x-session-context"] == context
    assert auth_cookie not in response.text
    replay = make(); replay.client.cookies.set(service.COOKIE, pre_cookie)
    assert replay.client.get("/documents").status_code == 401
    # Reusing a pre-login CSRF after rotation is rejected.
    assert a.upload(headers={"X-CSRF-Token": pre_csrf}).status_code == 403
    new_process = make(); new_process.client.cookies.set(service.COOKIE, auth_cookie)
    assert new_process.client.get("/auth/me").json()["session_context"] == context
    assert a.login().json()["session_context"] != context
    assert new_process.client.get("/auth/me").status_code == 401
    final_cookie = a.client.cookies.get(service.COOKIE)
    logout = a.post("/auth/logout")
    assert logout.status_code == 204 and "max-age=0" in logout.headers["set-cookie"].lower()
    replay.client.cookies.set(service.COOKIE, final_cookie)
    assert replay.client.get("/documents").status_code == 401
    assert a.post("/auth/logout").status_code == 204


@pytest.mark.parametrize("kind", ["missing", "malformed", "unknown", "idle", "absolute", "revoked"])
def test_invalid_sessions_fail_closed_with_controlled_time(browsers, kind):
    make, clock, database = browsers
    a = make(); a.account()
    if kind == "missing":
        a.client.cookies.clear()
    elif kind == "malformed":
        a.client.cookies.clear(); a.client.cookies.set(service.COOKIE, "x" * 129)
    elif kind == "unknown":
        a.client.cookies.clear(); a.client.cookies.set(service.COOKIE, "synthetic-unknown")
    elif kind == "idle":
        clock.advance(minutes=30)
    elif kind == "absolute":
        # Keep last_seen recent to isolate absolute expiry.
        clock.advance(hours=8)
        with database.engine.begin() as connection:
            connection.execute(update(AuthSession).values(last_seen_at=clock()))
    else:
        assert a.post("/auth/logout").status_code == 204
    assert a.client.get("/documents").status_code == a.upload().status_code == 401


def test_idle_activity_and_anonymous_expiry(browsers):
    make, clock, _ = browsers
    a = make(); a.bootstrap(); csrf = a.csrf
    assert a.bootstrap().json()["csrf_token"] == csrf
    clock.advance(minutes=10)
    assert a.post("/auth/register", json={"email": "x@example.com", "password": PASSWORD}).status_code == 403
    a.account()
    clock.advance(minutes=29)
    assert a.client.get("/documents").status_code == 200
    clock.advance(minutes=29)
    assert a.client.get("/auth/me").status_code == 200
    clock.advance(minutes=30)
    assert a.client.get("/auth/me").status_code == 401


@pytest.mark.parametrize("path", ["/auth/register", "/auth/login", "/auth/logout", "/documents"])
@pytest.mark.parametrize("attack", ["missing", "wrong", "other-session", "origin", "null", "no-origin"])
def test_csrf_rejection_for_every_write(browsers, path, attack):
    make, _, database = browsers
    a = make(); a.account()
    headers = {}
    if attack == "missing": headers["X-CSRF-Token"] = ""
    elif attack == "wrong": headers["X-CSRF-Token"] = "wrong"
    elif attack == "other-session":
        b = make(); b.bootstrap(); headers["X-CSRF-Token"] = b.csrf
    elif attack == "origin": headers["Origin"] = "http://evil.example"
    elif attack == "null": headers["Origin"] = "null"
    else: headers["Origin"] = ""
    response = a.post(path, headers=headers, json={"email": "new@example.com", "password": PASSWORD})
    assert response.status_code == 403 and count(database, Document) == 0
    assert a.client.get("/auth/me").status_code == 200


@pytest.mark.parametrize("headers", [{}, {"Origin": "null"}, {"Origin": "https://evil.example"},
                                      {"Origin": ORIGIN, "Sec-Fetch-Site": "cross-site"}])
def test_bootstrap_cross_site_rejected(browsers, headers):
    make, _, database = browsers
    response = make().client.get("/auth/csrf", headers=headers)
    assert response.status_code == 403 and count(database, AuthSession) == 0


def test_unauthorized_rejected_before_any_form_parser_or_body_read(browsers, monkeypatch):
    make, _, database = browsers
    def forbidden_parse(*args, **kwargs):
        raise AssertionError("Unauthenticated requests must never parse multipart")
    monkeypatch.setattr(MultiPartParser, "parse", forbidden_parse)
    a = make()
    assert a.upload().status_code == 401
    a.bootstrap()  # Anonymous CSRF context still cannot upload.
    assert a.upload().status_code == 401
    a.account()
    assert a.upload(headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert count(database, Document) == 0


def test_two_user_isolation_legacy_rows_and_public_context_is_not_credential(browsers):
    make, _, database = browsers
    with database.engine.begin() as connection:
        legacy = connection.scalar(insert(Document).values(original_filename="legacy.txt", content="legacy", original_byte_size=6).returning(Document.id))
    a, b = make(), make()
    a.account("a@example.com"); b.account("b@example.com")
    a_doc, b_doc = a.upload().json(), b.upload().json()
    assert a.client.get("/documents").json() == [a_doc]
    assert b.client.get("/documents").json() == [b_doc]
    assert a_doc["original_filename"] == b_doc["original_filename"] and a_doc["id"] != b_doc["id"]
    assert set(a_doc) == {"id", "original_filename", "byte_size", "created_at"}
    with database.engine.connect() as connection:
        assert connection.scalar(select(Document.owner_id).where(Document.id == legacy)) is None
    anon = make()
    context = a.client.get("/auth/me").json()["session_context"]
    anon.client.cookies.set(service.COOKIE, context)
    assert anon.client.get("/documents", headers={"X-Session-Context": context}).status_code == 401


@pytest.mark.parametrize("field", ["owner_id", "user_id"])
@pytest.mark.parametrize("place", ["form", "query", "json"])
def test_forged_ownership_fields_rejected(browsers, field, place):
    make, _, database = browsers
    a, b = make(), make(); a.account("a@example.com")
    other_id = b.account("b@example.com").json()["user"]["id"]
    if place == "form": response = a.upload(data={field: other_id})
    elif place == "query": response = a.upload(params={field: other_id})
    else: response = a.post("/documents", json={field: other_id, "file": "forged.txt"})
    assert response.status_code in {400, 422}
    assert count(database, Document) == 0


def test_login_email_rate_limit_canonical_fixed_window(browsers):
    make, clock, _ = browsers
    a = make(); a.bootstrap()
    responses = [a.login("Unknown@EXAMPLE.com") for _ in range(6)]
    assert [r.status_code for r in responses] == [401] * 5 + [429]
    assert int(responses[-1].headers["retry-after"]) > 0
    clock.advance(minutes=15)
    a.bootstrap()
    assert a.login("unknown@example.com").status_code == 401


def test_atomic_limiter_and_expired_window(browsers):
    _, clock, database = browsers
    def attempt(_):
        try:
            service.throttle(database.engine, database.settings, [("concurrent", "synthetic", 5, 60)], clock)
            return 200
        except service.AuthError as error:
            return error.status
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(12)))
    assert results.count(200) == 5 and results.count(429) == 7
    with database.engine.connect() as connection:
        assert connection.scalar(select(RateLimit.attempts)) == 6  # Saturates.
    clock.advance(minutes=1)
    assert attempt(0) == 200


@pytest.mark.parametrize("scope,maximum,seconds", [("login_ip", 20, 300), ("register_ip", 5, 3600), ("csrf_ip", 60, 60)])
def test_ip_budgets_boundary_without_sleep(browsers, scope, maximum, seconds):
    _, clock, database = browsers
    for _ in range(maximum):
        service.throttle(database.engine, database.settings, [(scope, "127.0.0.1", maximum, seconds)], clock)
    with pytest.raises(service.AuthError) as error:
        service.throttle(database.engine, database.settings, [(scope, "127.0.0.1", maximum, seconds)], clock)
    assert error.value.status == 429
    clock.advance(seconds=seconds)
    service.throttle(database.engine, database.settings, [(scope, "127.0.0.1", maximum, seconds)], clock)


def test_cleanup_bounded_preserves_live_sessions_and_counters(browsers):
    make, clock, database = browsers
    a, b = make(), make(); a.account()
    b.bootstrap()
    service.throttle(database.engine, database.settings, [("old", "synthetic", 2, 60)], clock)
    clock.advance(minutes=11)
    assert a.client.get("/auth/me").status_code == 200
    result = service.cleanup(database.engine, database.settings, clock, 1)
    assert result == {"sessions": 1, "rate_limits": 1}
    assert a.client.get("/documents").status_code == 200
    clock.advance(days=2)
    result = service.cleanup(database.engine, database.settings, clock, 1)
    assert result["sessions"] <= 1 and result["rate_limits"] == 1
    with pytest.raises(ValueError): service.cleanup(database.engine, database.settings, clock, 1001)


def test_database_failures_are_sanitized_and_fail_closed(browsers, caplog):
    make, _, database = browsers
    a = make(); a.account()
    def fail(*args):
        raise OperationalError("private synthetic SQL", {"password": PASSWORD}, Exception("private synthetic token"))
    event.listen(a.app.state.engine, "before_cursor_execute", fail)
    for path in ["/auth/csrf", "/auth/me", "/documents"]:
        response = a.client.get(path, headers={"Origin": ORIGIN})
        assert response.status_code == 503
        assert PASSWORD not in response.text + caplog.text and "synthetic" not in response.text + caplog.text
    response = a.post("/auth/logout")
    assert response.status_code == 503 and "set-cookie" not in response.headers
    event.remove(a.app.state.engine, "before_cursor_execute", fail)
    assert a.client.get("/auth/me").status_code == 200


def test_login_commit_failure_rolls_back_rotation_and_cookie(browsers, caplog):
    make, _, database = browsers
    a = make(); a.account()
    old = a.client.cookies.get(service.COOKIE)
    old_digest = service.digest(old)
    def fail(connection):
        # Ignore guard/limiter/read commits. Fail only the rotation transaction.
        revoked = connection.scalar(select(AuthSession.revoked_at).where(AuthSession.token_digest == old_digest))
        if revoked is not None:
            with database.engine.connect() as separate:
                assert separate.scalar(select(AuthSession.revoked_at).where(AuthSession.token_digest == old_digest)) is None
            raise OperationalError("synthetic-secret-SQL", {}, Exception(PASSWORD))
    event.listen(a.app.state.engine, "commit", fail)
    response = a.login()
    assert response.status_code == 503 and "set-cookie" not in response.headers
    assert a.client.cookies.get(service.COOKIE) == old and PASSWORD not in response.text + caplog.text
    event.remove(a.app.state.engine, "commit", fail)
    assert a.client.get("/auth/me").status_code == 200


def test_logout_commit_failure_does_not_claim_success(browsers):
    make, _, _ = browsers
    a = make(); a.account()
    def fail(connection):
        raise OperationalError("synthetic SQL", {}, Exception("synthetic secret"))
    event.listen(a.app.state.engine, "commit", fail)
    response = a.post("/auth/logout")
    assert response.status_code == 503 and "set-cookie" not in response.headers
    event.remove(a.app.state.engine, "commit", fail)
    assert a.client.get("/auth/me").status_code == 200


def test_http_csrf_budget_peer_ip_not_forwarded_header(browsers):
    make, _, _ = browsers
    a = make()
    responses = [a.client.get("/auth/csrf", headers={"Origin": ORIGIN, "X-Forwarded-For": f"192.0.2.{number}"}) for number in range(61)]
    assert all(response.status_code == 200 for response in responses[:-1])
    assert responses[-1].status_code == 429


def test_http_registration_limit_counts_duplicate_attempts(browsers):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    results = [a.post("/auth/register", json={"email": "student@example.com", "password": PASSWORD}) for _ in range(6)]
    assert [r.status_code for r in results] == [202] * 5 + [429]


def test_http_login_ip_limit_includes_unknown_identifiers(browsers):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    results = [a.login(f"unknown{number}@example.com") for number in range(21)]
    assert [r.status_code for r in results] == [401] * 20 + [429]


def test_registration_commit_failure_no_partial_user(browsers, caplog):
    make, _, database = browsers
    a = make(); a.bootstrap()
    def fail(connection, cursor, statement, *args):
        if statement.startswith("INSERT INTO users"):
            with database.engine.connect() as other:
                assert other.scalar(select(func.count()).select_from(User)) == 0
            raise OperationalError("synthetic SQL", {"password": PASSWORD}, Exception("synthetic secret"))
    event.listen(a.app.state.engine, "after_cursor_execute", fail)
    response = a.post("/auth/register", json={"email": "student@example.com", "password": PASSWORD})
    assert response.status_code == 503 and count(database, User) == 0
    assert PASSWORD not in response.text + caplog.text
    event.remove(a.app.state.engine, "after_cursor_execute", fail)


def test_concurrent_login_only_rotates_prior_context_once(browsers):
    make, _, _ = browsers
    a = make(); a.account()
    b = make()
    b.client.cookies.set(service.COOKIE, a.client.cookies.get(service.COOKIE))
    b.csrf = a.csrf
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda browser: browser.login(), [a, b]))
    assert sorted(response.status_code for response in results) == [200, 403]


def test_successful_login_upgrades_hash_profile(browsers):
    from pwdlib import PasswordHash
    from pwdlib.hashers.argon2 import Argon2Hasher
    make, _, database = browsers
    a = make(); a.account()
    # Synthetic historical profile, only inside this private test schema.
    older = PasswordHash((Argon2Hasher(memory_cost=19456, time_cost=2, parallelism=1),)).hash(PASSWORD)
    with database.engine.begin() as connection:
        connection.execute(update(User).values(password_hash=older))
    assert a.login().status_code == 200
    with database.engine.connect() as connection:
        assert "m=65536,t=3,p=4" in connection.scalar(select(User.password_hash))


def test_unauthenticated_asgi_upload_does_not_receive_body(browsers):
    import asyncio
    make, _, _ = browsers
    a = make()
    messages = []
    async def never_receive():
        raise AssertionError("Body read before authentication")
    async def send(message):
        messages.append(message)
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "POST", "scheme": "http", "path": "/documents", "raw_path": b"/documents",
             "query_string": b"", "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
             "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 12345)}
    asyncio.run(a.app(scope, never_receive, send))
    assert messages[0]["status"] == 401


def test_aliases_are_not_collapsed_and_multibyte_password_limit():
    assert Credentials(email="a.b+study@example.com", password=PASSWORD).identity()[1] == "a.b+study@example.com"
    assert Credentials(email="ab@example.com", password=PASSWORD).identity()[1] == "ab@example.com"
    assert Credentials(email="ab@example.com", password="😀" * 128).password.get_secret_value() == "😀" * 128


def test_limiter_store_failure_blocks_hashing(browsers, monkeypatch):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    from app.auth import security
    def no_hash(*args):
        raise AssertionError("Limiter failure must precede expensive hashing")
    def fail(connection, cursor, statement, *args):
        if statement.startswith("INSERT INTO auth_rate_limits"):
            raise OperationalError("synthetic", {}, Exception("synthetic"))
    monkeypatch.setattr(service, "hash_password", no_hash)
    event.listen(a.app.state.engine, "before_cursor_execute", fail)
    assert a.post("/auth/register", json={"email": "student@example.com", "password": PASSWORD}).status_code == 503
    event.remove(a.app.state.engine, "before_cursor_execute", fail)


def test_anonymous_logout_requires_csrf_but_missing_session_still_requires_origin(browsers):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    assert a.post("/auth/logout", headers={"X-CSRF-Token": "wrong"}).status_code == 403
    assert a.post("/auth/logout").status_code == 204
    assert a.post("/auth/logout", headers={"Origin": ""}).status_code == 403


def test_unknown_account_uses_password_verification_work(browsers, monkeypatch):
    make, _, _ = browsers
    a = make(); a.bootstrap()
    original, called = service.verify_password, []
    def verify(value, encoded):
        called.append(encoded is None)
        return original(value, encoded)
    monkeypatch.setattr(service, "verify_password", verify)
    assert a.login("unknown@example.com").status_code == 401
    assert called == [True]


def test_unsupported_document_methods_do_not_enter_write_guard(browsers):
    make, _, _ = browsers
    a = make()
    response = a.client.request("DELETE", "/documents", headers={"Origin": ORIGIN, "X-CSRF-Token": "synthetic"})
    assert response.status_code == 405
