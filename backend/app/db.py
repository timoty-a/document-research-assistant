"""Synchronous SQLAlchemy access and project database ownership checks."""

from sqlalchemy import Connection, Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase

from app.config import Settings


class Base(DeclarativeBase):
    pass


def create_db_engine(settings: Settings) -> Engine:
    # Creating an engine is lazy; it does not open a database connection.
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        hide_parameters=True,
        connect_args={"connect_timeout": 3},
    )


def assert_project_database(connection: Connection, settings: Settings) -> None:
    """Refuse DDL/test writes unless name, owner, role and project marker match."""
    row = connection.execute(text("""
        SELECT current_database() AS name, current_user AS role,
               pg_get_userbyid(d.datdba) AS owner,
               shobj_description(d.oid, 'pg_database') AS marker,
               r.rolsuper, r.rolcreatedb, r.rolcreaterole, r.rolreplication,
               r.rolbypassrls
        FROM pg_database AS d
        JOIN pg_roles AS r ON r.rolname = current_user
        WHERE d.datname = current_database()
    """)).mappings().one()
    marker = f"document-research-assistant:{settings.app_env}"
    if (
        row["name"] != settings.db_name
        or row["role"] != settings.db_user
        or row["owner"] != settings.db_user
        or row["marker"] != marker
        or any(row[key] for key in (
            "rolsuper", "rolcreatedb", "rolcreaterole", "rolreplication", "rolbypassrls"
        ))
    ):
        raise RuntimeError("Refusing access: database ownership or project identity mismatch")
