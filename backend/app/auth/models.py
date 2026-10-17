"""Persistent authentication state; raw session credentials are never stored."""
from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, LargeBinary, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint("octet_length(email_key) BETWEEN 3 AND 254 AND email_key = lower(email_key)", name="ck_users_email_key"),
        CheckConstraint("length(email) BETWEEN 3 AND 320", name="ck_users_email"),
        CheckConstraint("length(password_hash) BETWEEN 1 AND 512", name="ck_users_password_hash"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    email: Mapped[str] = mapped_column(Text)
    email_key: Mapped[str] = mapped_column(Text(collation="C"), unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint("octet_length(token_digest) = 32", name="ck_sessions_digest"),
        CheckConstraint("length(csrf_token) BETWEEN 32 AND 128", name="ck_sessions_csrf"),
        CheckConstraint("last_seen_at >= created_at AND expires_at > created_at AND (revoked_at IS NULL OR revoked_at >= created_at)", name="ck_sessions_dates"),
    )
    token_digest: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", ondelete="RESTRICT"), index=True)
    csrf_token: Mapped[str] = mapped_column(Text)
    session_context: Mapped[UUID] = mapped_column(unique=True, server_default=text("gen_random_uuid()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RateLimit(Base):
    __tablename__ = "auth_rate_limits"
    __table_args__ = (
        CheckConstraint("attempts >= 0", name="ck_rate_attempts"),
        CheckConstraint("expires_at > window_start", name="ck_rate_dates"),
        CheckConstraint("length(scope) BETWEEN 1 AND 32 AND length(key) BETWEEN 1 AND 254", name="ck_rate_key"),
    )
    scope: Mapped[str] = mapped_column(Text, primary_key=True)
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    attempts: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
