"""Run migrations only against verified project-owned local databases."""
from alembic import context
from app.config import Settings
from app.db import Base, assert_project_database, create_db_engine
from app.documents.models import Document  # noqa: F401
from app.auth.models import User, AuthSession, RateLimit  # noqa: F401

settings = context.config.attributes.get("settings") or Settings()
target_metadata = Base.metadata


def migrate(connection):
    assert_project_database(connection, settings)
    # Test callers provide an explicit transaction/search_path; leave it intact.
    if "connection" not in context.config.attributes:
        connection.rollback()
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    context.configure(dialect_name="postgresql", target_metadata=target_metadata,
                      literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()
elif "connection" in context.config.attributes:
    migrate(context.config.attributes["connection"])
else:
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            migrate(connection)
    finally:
        engine.dispose()
