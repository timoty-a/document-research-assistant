from uuid import UUID

import pytest
from sqlalchemy import inspect, insert
from sqlalchemy.exc import IntegrityError

from app.documents.models import Document

pytestmark = pytest.mark.database


def test_migrated_schema(db_connection):
    inspector = inspect(db_connection)
    columns = {column["name"]: column for column in inspector.get_columns("documents")}
    assert set(columns) == {"id", "original_filename", "content", "original_byte_size", "created_at", "owner_id"}
    assert columns["owner_id"]["nullable"]
    assert all(not column["nullable"] for name, column in columns.items() if name != "owner_id")
    assert inspector.get_pk_constraint("documents")["constrained_columns"] == ["id"]
    assert columns["created_at"]["type"].timezone is True
    assert len(inspector.get_check_constraints("documents")) == 5


@pytest.mark.parametrize("content", ["  héllo\n", "x" * 1048576])
def test_valid_text_is_preserved_with_generated_metadata(db_connection, content):
    row = db_connection.execute(insert(Document).values(
        original_filename="synthetic.TXT", content=content,
        original_byte_size=len(content.encode("utf-8")),
    ).returning(Document.__table__)).mappings().one()
    assert isinstance(row["id"], UUID)
    assert row["content"] == content
    assert row["created_at"].utcoffset() is not None


@pytest.mark.parametrize("filename,content,size", [
    ("empty.txt", "", 0),
    ("space.txt", " \t\n", 3),
    ("unicode.txt", "\u2003\u00a0", 5),
    ("wrong.pdf", "x", 1),
    ("", "x", 1),
    ("large.txt", "x" * 1048577, 1048577),
    ("mismatch.txt", "é", 1),
    ("null.txt", None, 1),
])
def test_invalid_rows_are_rejected_atomically(db_connection, filename, content, size):
    before = db_connection.exec_driver_sql("SELECT count(*) FROM documents").scalar_one()
    with pytest.raises(IntegrityError):
        with db_connection.begin_nested():
            db_connection.execute(insert(Document).values(
                original_filename=filename, content=content, original_byte_size=size,
            ))
    after = db_connection.exec_driver_sql("SELECT count(*) FROM documents").scalar_one()
    assert after == before
