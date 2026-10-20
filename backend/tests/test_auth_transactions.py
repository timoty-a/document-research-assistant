"""Real migration and lock-order checks using controlled time, not sleeps."""
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, inspect, insert, select, text
from sqlalchemy.exc import IntegrityError, OperationalError

from conftest import BACKEND, isolated_database, migrate
from auth_helpers import Browser, Clock, PASSWORD
from app.auth import service
from app.auth.models import AuthSession
from app.documents import service as documents
from app.documents.models import Document
from app.documents.validation import ValidatedDocument

pytestmark = pytest.mark.database


def test_migration_preserves_populated_legacy_and_refuses_downgrade(test_settings):
    with isolated_database(test_settings, "0001_documents") as database:
        with database.engine.begin() as connection:
            before = connection.execute(insert(Document.__table__).values(
                original_filename="legacy.TXT", content="  synthetic\r\n", original_byte_size=13,
            ).returning(Document.id, Document.original_filename, Document.content,
                        Document.original_byte_size, Document.created_at)).mappings().one()
        migrate(database.engine, test_settings)
        with database.engine.connect() as connection:
            after = connection.execute(select(Document.__table__)).mappings().one()
            assert {k: after[k] for k in before} == dict(before) and after["owner_id"] is None
            from scripts.check_schema import check_schema
            check_schema(connection, test_settings)
        migrate(database.engine, test_settings)  # Safe repeat: already at head.
        browser = Browser(database, Clock())
        try:
            browser.account()
            assert browser.client.get("/documents").json() == []
            with database.engine.begin() as connection:
                with pytest.raises(IntegrityError):
                    with connection.begin_nested():
                        connection.execute(text("UPDATE documents SET owner_id = gen_random_uuid()"))
            with pytest.raises(RuntimeError, match="downgrade refused"):
                with database.engine.begin() as connection:
                    config = Config(str(BACKEND / "alembic.ini"))
                    config.attributes.update(connection=connection, settings=test_settings)
                    command.downgrade(config, "0001_documents")
            with database.engine.connect() as connection:
                assert connection.scalar(select(Document.content)) == before["content"]
                assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0003_pdf_documents"
        finally:
            browser.client.close(); browser.app.state.engine.dispose()


def test_failed_migration_rolls_back_ddl_and_can_resume(test_settings):
    with isolated_database(test_settings, "0001_documents") as database:
        with database.engine.begin() as connection:
            connection.exec_driver_sql("INSERT INTO documents(original_filename,content,original_byte_size) VALUES ('legacy.txt','synthetic',9)")
        def fail(connection, cursor, statement, *args):
            if statement.startswith("ALTER TABLE documents ADD COLUMN owner_id"):
                raise OperationalError("synthetic migration fault", {}, Exception("synthetic"))
        event.listen(database.engine, "before_cursor_execute", fail)
        with pytest.raises(OperationalError):
            migrate(database.engine, test_settings)
        event.remove(database.engine, "before_cursor_execute", fail)
        with database.engine.connect() as connection:
            assert set(inspect(connection).get_table_names()) == {"documents", "alembic_version"}
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001_documents"
            assert connection.scalar(text("SELECT content FROM documents")) == "synthetic"
        migrate(database.engine, test_settings)
        with database.engine.connect() as connection:
            assert connection.scalar(select(Document.owner_id)) is None


@pytest.mark.parametrize("first", ["write", "logout", "expiry"])
def test_session_lock_orders_logout_and_document_write(browsers, first):
    make, clock, database = browsers
    a = make(); a.account()
    raw = a.client.cookies.get(service.COOKIE)
    token = service.digest(raw)
    document = ValidatedDocument("synthetic.txt", "synthetic", 9)
    locked, release, waiting = Event(), Event(), Event()
    first_engine, second_engine = database.make_engine(), database.make_engine()
    # Hold the first transaction after it has locked and changed state, then
    # observe the second reaching FOR UPDATE. No wall-clock sleeps are used.
    def hold_commit(connection):
        locked.set()
        assert release.wait(10)
    def second_lock(connection, cursor, statement, *args):
        if "FOR UPDATE" in statement:
            waiting.set()
    event.listen(first_engine, "commit", hold_commit)
    event.listen(second_engine, "before_cursor_execute", second_lock)

    def write(engine):
        try:
            documents.save_document(engine, database.settings, document, token, a.csrf, clock)
            return 201
        except service.AuthError as error:
            return error.status

    def logout(engine):
        service.logout(engine, database.settings, raw, a.csrf, clock)
        return 204

    def hold_session():
        with service.transaction(first_engine, database.settings) as connection:
            service.require_session(connection, token, clock)
        return 200

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            initial = pool.submit(write if first == "write" else logout if first == "logout" else hold_session, first_engine) if first != "expiry" else pool.submit(hold_session)
            assert locked.wait(10)
            pending = pool.submit(logout if first == "write" else write, second_engine)
            assert waiting.wait(10)
            if first == "expiry": clock.advance(minutes=30)
            release.set()
            assert initial.result(10) == {"write": 201, "logout": 204, "expiry": 200}[first]
            assert pending.result(10) == (204 if first == "write" else 401)
        with database.engine.connect() as connection:
            rows = connection.execute(select(Document.id)).all()
            assert len(rows) == (1 if first == "write" else 0)
    finally:
        release.set()
        event.remove(first_engine, "commit", hold_commit)
        event.remove(second_engine, "before_cursor_execute", second_lock)


def test_cleanup_skips_locked_live_activity(browsers):
    make, clock, database = browsers
    a = make(); a.account()
    token = service.digest(a.client.cookies.get(service.COOKIE))
    clock.advance(minutes=29)
    with database.engine.begin() as connection:
        service.require_session(connection, token, clock)
        clock.advance(minutes=2)
        # The committed snapshot looks idle-expired, but the locked activity
        # update keeps the session valid. A concurrent cleanup skips this row; no valid session is deleted.
        result = service.cleanup(database.engine, database.settings, clock, 1000)
        assert result["sessions"] <= 1  # May remove the revoked pre-session.
    assert a.client.get("/auth/me").status_code == 200


def test_alembic_check_matches_live_migrated_models(auth_database):
    with auth_database.engine.begin() as connection:
        config = Config(str(BACKEND / "alembic.ini"))
        config.attributes.update(connection=connection, settings=auth_database.settings)
        command.check(config)
