import asyncio
from datetime import datetime, timezone
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, insert, select
from sqlalchemy.exc import OperationalError

from app.documents.models import Document

pytestmark = pytest.mark.database
METADATA_KEYS = {"id", "original_filename", "byte_size", "created_at"}


def request(app, method, path="/documents", **kwargs):
    async def run():
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                raw, csrf = app.state.test_auth
                client.cookies.set("dra_session", raw)
                headers = {"Origin": "http://127.0.0.1:8000", "X-CSRF-Token": csrf, **kwargs.pop("headers", {})}
                return await client.request(method, path, headers=headers, **kwargs)
    return asyncio.run(run())


def row_count(engine):
    with engine.connect() as connection:
        return connection.scalar(select(func.count()).select_from(Document))


def test_upload_preserves_exact_text_and_lists_metadata_only(api_database):
    app = api_database.make_app()
    content = "\ufeff  Café\r\n\u2003document passage\t  "
    payload = content.encode("utf-8")
    response = request(app, "POST", files={"file": ("../synthetic.TXT", payload, "text/plain")})
    assert response.status_code == 201
    metadata = response.json()
    assert set(metadata) == METADATA_KEYS
    assert metadata["original_filename"] == "../synthetic.TXT"
    assert metadata["byte_size"] == len(payload) != len(content)
    assert datetime.fromisoformat(metadata["created_at"]).utcoffset() is not None
    with api_database.engine.connect() as connection:
        row = connection.execute(select(Document.__table__)).mappings().one()
        assert row["id"] == UUID(metadata["id"])
        assert row["content"] == content
        assert row["original_byte_size"] == len(payload)
    listing = request(app, "GET")
    assert listing.status_code == 200
    assert listing.json() == [metadata]


def test_empty_list(api_database):
    response = request(api_database.make_app(), "GET")
    assert response.status_code == 200
    assert response.json() == []


def test_deterministic_ordering_and_metadata_projection(api_database):
    older = datetime(2026, 1, 1, tzinfo=timezone.utc)
    later = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with api_database.engine.begin() as connection:
        for number, timestamp in [(3, later), (2, older), (1, older)]:
            connection.execute(insert(Document).values(
                owner_id=api_database.user_id, id=UUID(int=number), original_filename=f"synthetic-{number}.txt",
                content="synthetic content", original_byte_size=17, created_at=timestamp,
            ))
    app = api_database.make_app()
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT") and "FROM documents" in statement:
            statements.append(statement)

    event.listen(app.state.engine, "before_cursor_execute", capture)
    first = request(app, "GET")
    second = request(app, "GET")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert [UUID(row["id"]).int for row in first.json()] == [1, 2, 3]
    assert all(set(row) == METADATA_KEYS for row in first.json())
    assert len(statements) == 2
    assert all("content" not in sql.lower() and "*" not in sql and "documents.owner_id =" in sql for sql in statements)


@pytest.mark.parametrize("filename,payload,status,message", [
    ("empty.txt", b"", 400, "non-whitespace"),
    ("space.txt", b" \t\r\n", 400, "non-whitespace"),
    ("unicode.txt", "\u2003\u00a0".encode(), 400, "non-whitespace"),
    ("wrong.pdf", b"synthetic", 400, ".txt"),
    ("invalid.txt", b"\xff\xfe", 400, "UTF-8"),
    ("null.txt", b"a\x00b", 400, "null"),
    ("large.txt", b"x" * 1048577, 413, "1,048,576"),
])
def test_rejections_leave_no_record(api_database, filename, payload, status, message):
    response = request(api_database.make_app(), "POST", files={"file": (filename, payload)})
    assert response.status_code == status
    assert message in response.json()["detail"]
    assert row_count(api_database.engine) == 0


@pytest.mark.parametrize("filename", ["", "invalid\x00.txt"])
def test_invalid_raw_filename_is_client_error(api_database, filename):
    # HTTPX omits empty names and percent-escapes NUL. Send actual invalid
    # metadata to exercise server validation rather than client rewriting.
    boundary = "synthetic-boundary"
    body = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f'Content-Type: text/plain\r\n\r\nsynthetic\r\n--{boundary}--\r\n'
    ).encode()
    response = request(api_database.make_app(), "POST", content=body,
                       headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    assert response.status_code == 400
    assert row_count(api_database.engine) == 0


def test_long_filename_is_metadata_not_filesystem_name(api_database):
    filename = "a" * 300 + ".txt"
    response = request(api_database.make_app(), "POST", files={"file": (filename, b"synthetic")})
    assert response.status_code == 201
    assert response.json()["original_filename"] == filename


def test_exactly_one_mib_is_accepted(api_database):
    response = request(api_database.make_app(), "POST", files={"file": ("boundary.txt", b"x" * 1048576)})
    assert response.status_code == 201
    assert response.json()["byte_size"] == 1048576
    assert set(response.json()) == METADATA_KEYS


def test_missing_file_preserves_framework_validation(api_database):
    response = request(api_database.make_app(), "POST")
    assert response.status_code == 422
    assert response.json()["detail"][0]["loc"] == ["body", "file"]
    assert row_count(api_database.engine) == 0


@pytest.mark.parametrize("second_field", ["file", "other"])
def test_multiple_uploads_rejected(api_database, second_field):
    response = request(api_database.make_app(), "POST", files=[
        ("file", ("one.txt", b"synthetic")), (second_field, ("two.txt", b"synthetic")),
    ])
    assert response.status_code == 400
    assert row_count(api_database.engine) == 0


@pytest.mark.parametrize("failure_stage", ["after_write", "commit"])
def test_failure_before_commit_rolls_back_and_does_not_leak(api_database, caplog, failure_stage):
    app = api_database.make_app()
    observed = []
    sensitive = "synthetic-private-filename.txt synthetic-private-content synthetic-private-password"

    def fail(connection, *args):
        if failure_stage == "after_write":
            statement = args[1]
            if not statement.lstrip().upper().startswith("INSERT"):
                return
        if connection.scalar(select(func.count()).select_from(Document)) == 0:
            return  # Ignore the earlier authentication transaction.
        assert connection.scalar(select(func.count()).select_from(Document)) == 1
        # An independent connection cannot see the uncommitted write.
        observed.append(row_count(api_database.engine))
        raise OperationalError("synthetic-private-SQL", {"secret": sensitive}, Exception(sensitive))

    event_name = "after_cursor_execute" if failure_stage == "after_write" else "commit"
    event.listen(app.state.engine, event_name, fail)
    response = request(app, "POST", files={"file": ("synthetic-private-filename.txt", b"synthetic-private-content")})
    assert response.status_code == 503
    assert "unavailable" in response.text
    assert observed == [0]
    assert row_count(api_database.engine) == 0
    for token in sensitive.split() + ["synthetic-private-SQL"]:
        assert token not in response.text
        assert token not in caplog.text
    event.remove(app.state.engine, event_name, fail)
    # The resource remains usable after the failure, with a fresh transaction.
    assert request(app, "POST", files={"file": ("recovery.txt", b"synthetic")}).status_code == 201


def test_list_database_failure_is_sanitized(api_database, caplog):
    app = api_database.make_app()

    def fail(*args):
        raise OperationalError("synthetic-private-SQL", {}, Exception("synthetic-private-password"))

    event.listen(app.state.engine, "before_cursor_execute", fail)
    response = request(app, "GET")
    assert response.status_code == 503
    assert "unavailable" in response.text
    assert "synthetic-private" not in response.text + caplog.text


def test_commit_survives_fresh_application_and_connection(api_database):
    first_app = api_database.make_app()
    uploaded = request(first_app, "POST", files={"file": ("persistent.txt", b"synthetic persisted text")})
    assert uploaded.status_code == 201
    # Its lifespan has disposed the first engine. New app/engine means a new
    # physical connection; no process-local document cache can satisfy this.
    second_app = api_database.make_app()
    listing = request(second_app, "GET")
    assert listing.status_code == 200
    assert listing.json() == [uploaded.json()]
    fresh_engine = api_database.make_engine()
    with fresh_engine.connect() as connection:
        assert connection.scalar(select(Document.content)) == "synthetic persisted text"
