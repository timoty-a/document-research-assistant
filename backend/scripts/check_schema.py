"""Read-only identity, model/migration and constraint verification."""
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.auth.models import AuthSession, RateLimit, User  # noqa: F401
from app.documents.models import Document  # noqa: F401
from app.config import Settings
from app.db import Base, assert_project_database, create_db_engine


def check_schema(connection, settings):
    assert_project_database(connection, settings)
    revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    if revision != "0002_auth":
        raise RuntimeError("Expected auth migration; do not migrate development without the reviewed backup procedure")
    differences = compare_metadata(MigrationContext.configure(connection, opts={"compare_type": True, "compare_server_default": True}), Base.metadata)
    if differences:
        raise RuntimeError("Migration/model differences detected")
    inspector = inspect(connection)
    for table in Base.metadata.tables.values():
        expected = {c.name for c in table.constraints if c.__class__.__name__ == "CheckConstraint"}
        actual = {c["name"] for c in inspector.get_check_constraints(table.name)}
        if expected != actual:
            raise RuntimeError("Database check constraints differ from model")
    columns = {c["name"]: c for c in inspector.get_columns("documents")}
    if not columns["owner_id"]["nullable"] or not columns["created_at"]["type"].timezone:
        raise RuntimeError("Ownership nullability or timezone differs")


def main():
    settings = Settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            check_schema(connection, settings)
        print("PASS: project identity, auth/document schema, constraints and migration/model consistency")
    except (SQLAlchemyError, RuntimeError):
        raise SystemExit("Schema verification failed; check identity, migrations and model consistency") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
