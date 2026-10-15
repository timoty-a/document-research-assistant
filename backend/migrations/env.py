"""Run migrations only against verified project-owned local databases."""

from alembic import context

from app.config import Settings
from app.db import Base, assert_project_database, create_db_engine
from app.documents.models import Document  # noqa: F401 -- register metadata

settings = Settings()
target_metadata = Base.metadata

if context.is_offline_mode():
    context.configure(
        dialect_name="postgresql",
        target_metadata=target_metadata,
        literal_binds=True,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            assert_project_database(connection, settings)
            # The read-only guard started a transaction; finish it before Alembic's.
            connection.rollback()
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                compare_type=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()
