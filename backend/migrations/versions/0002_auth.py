"""Accounts and operational auth state; preserve unassigned historical sources.

Revision ID: 0002_auth
Revises: 0001_documents
"""
from alembic import op
import sqlalchemy as sa

revision = "0002_auth"
down_revision = "0001_documents"
branch_labels = depends_on = None


def upgrade():
    op.create_table("users",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_key", sa.Text(collation="C"), nullable=False, unique=True),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("email_verified_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("octet_length(email_key) BETWEEN 3 AND 254 AND email_key = lower(email_key)", name="ck_users_email_key"),
        sa.CheckConstraint("length(email) BETWEEN 3 AND 320", name="ck_users_email"),
        sa.CheckConstraint("length(password_hash) BETWEEN 1 AND 512", name="ck_users_password_hash"),
    )
    op.create_table("auth_sessions",
        sa.Column("token_digest", sa.LargeBinary(), primary_key=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT")),
        sa.Column("csrf_token", sa.Text(), nullable=False),
        sa.Column("session_context", sa.Uuid(), nullable=False, unique=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("octet_length(token_digest) = 32", name="ck_sessions_digest"),
        sa.CheckConstraint("length(csrf_token) BETWEEN 32 AND 128", name="ck_sessions_csrf"),
        sa.CheckConstraint("last_seen_at >= created_at AND expires_at > created_at AND (revoked_at IS NULL OR revoked_at >= created_at)", name="ck_sessions_dates"),
    )
    op.create_index("ix_auth_sessions_user_id", "auth_sessions", ["user_id"])
    op.create_index("ix_auth_sessions_expires_at", "auth_sessions", ["expires_at"])
    op.create_table("auth_rate_limits",
        sa.Column("scope", sa.Text(), primary_key=True), sa.Column("key", sa.Text(), primary_key=True),
        sa.Column("window_start", sa.DateTime(timezone=True), primary_key=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("attempts >= 0", name="ck_rate_attempts"),
        sa.CheckConstraint("expires_at > window_start", name="ck_rate_dates"),
        sa.CheckConstraint("length(scope) BETWEEN 1 AND 32 AND length(key) BETWEEN 1 AND 254", name="ck_rate_key"),
    )
    op.create_index("ix_auth_rate_limits_expires_at", "auth_rate_limits", ["expires_at"])
    op.add_column("documents", sa.Column("owner_id", sa.Uuid(), nullable=True))
    op.create_foreign_key("fk_documents_owner", "documents", "users", ["owner_id"], ["id"], ondelete="RESTRICT")
    op.create_index("ix_documents_owner_created_id", "documents", ["owner_id", "created_at", "id"])


def downgrade():
    # Returning to the old application would expose every private document.
    # Never silently discard accounts or ownership, even when tables look empty.
    raise RuntimeError("Auth downgrade refused: use a reviewed forward fix or a consistent private backup")
