"""Read-only schema verification for the configured project database."""

from sqlalchemy import DateTime, Integer, Text, Uuid, inspect, text
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.db import assert_project_database, create_db_engine


def main() -> None:
    settings = Settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            assert_project_database(connection, settings)
            inspector = inspect(connection)
            columns = {c["name"]: c for c in inspector.get_columns("documents")}
            expected = {"id", "original_filename", "content", "original_byte_size", "created_at"}
            if set(columns) != expected or any(c["nullable"] for c in columns.values()):
                raise RuntimeError("Document columns or nullability do not match")
            expected_types = {
                "id": Uuid, "original_filename": Text, "content": Text,
                "original_byte_size": Integer, "created_at": DateTime,
            }
            if any(not isinstance(columns[name]["type"], kind) for name, kind in expected_types.items()):
                raise RuntimeError("Document column types do not match")
            if inspector.get_pk_constraint("documents")["constrained_columns"] != ["id"]:
                raise RuntimeError("Document primary key does not match")
            if not columns["created_at"]["type"].timezone:
                raise RuntimeError("Creation timestamp must have timezone support")
            constraints = {c["name"] for c in inspector.get_check_constraints("documents")}
            expected_constraints = {
                "ck_documents_filename_nonempty", "ck_documents_txt_extension",
                "ck_documents_byte_size", "ck_documents_content_nonblank", "ck_documents_utf8_byte_size",
            }
            if constraints != expected_constraints:
                raise RuntimeError("Document check constraints do not match")
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
            if revision != "0001_documents":
                raise RuntimeError("Unexpected migration revision")
        print("PASS: project identity, document schema, constraints and migration revision")
    except SQLAlchemyError:
        raise SystemExit("Database verification failed: check provisioning, credentials and migrations") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
