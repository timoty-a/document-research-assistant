"""Real PDF parsing and transactional persistence in isolated dra_test schemas."""
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import event, func, insert, select, text
from sqlalchemy.exc import OperationalError, IntegrityError

from app.documents import pdf
from app.documents.models import Document, DocumentPage
from app.documents.body_limit import MAX_BODY_BYTES
from conftest import BACKEND, isolated_database, migrate
from pdf_samples import pdf_bytes
from test_documents_api import request, row_count

pytestmark = pytest.mark.database


def test_pdf_source_pages_metadata_projection_and_fresh_connection(api_database):
    app = api_database.make_app()
    source = pdf_bytes(('Café evidence.', None, 'Final finding.'))
    response = request(app, 'POST', files={'file': ('../same.PDF', source, 'text/plain')})
    assert response.status_code == 201
    metadata = response.json()
    assert metadata['source_format'] == 'pdf' and metadata['page_count'] == 3
    assert metadata['textless_pages'] == [2] and metadata['byte_size'] == len(source)
    assert set(metadata) == {'id', 'original_filename', 'byte_size', 'created_at', 'source_format', 'page_count', 'textless_pages'}
    with api_database.make_engine().connect() as connection:
        row = connection.execute(select(Document.__table__)).mappings().one()
        assert row['source_pdf'] == source and row['original_byte_size'] == len(source)
        assert row['content'] == 'Café evidence.\n\f\n\n\f\nFinal finding.'
        assert row['extraction_version'] == pdf.PROFILE and row['owner_id'] == api_database.user_id
        pages = connection.execute(select(DocumentPage.page_number, DocumentPage.text, DocumentPage.has_text).order_by(DocumentPage.page_number)).all()
        assert pages == [(1, 'Café evidence.', True), (2, '', False), (3, 'Final finding.', True)]
    fresh = api_database.make_app()
    statements = []
    def capture(connection, cursor, statement, *args):
        if 'FROM documents' in statement:
            statements.append(statement)
    event.listen(fresh.state.engine, 'before_cursor_execute', capture)
    assert request(fresh, 'GET').json() == [metadata]
    assert all('documents.content' not in sql and 'source_pdf' not in sql and 'document_pages.text' not in sql for sql in statements)
    assert len(statements) == 1


@pytest.mark.parametrize('kind,status,code', [
    ('encrypted', 400, 'pdf_encrypted'), ('empty-password', 400, 'pdf_encrypted'),
    ('blank', 400, 'pdf_no_text'), ('malformed', 400, 'pdf_invalid'),
    ('truncated', 400, 'pdf_invalid'), ('pages', 413, 'pdf_limit_exceeded'),
])
def test_pdf_rejections_are_atomic_and_sanitized(api_database, kind, status, code, caplog):
    source = {
        'encrypted': lambda: pdf_bytes(password='synthetic-only'),
        'empty-password': lambda: pdf_bytes(password=''),
        'blank': lambda: pdf_bytes((None,)), 'malformed': lambda: b'%PDF-private invalid data',
        'truncated': lambda: pdf_bytes()[:100],
        'pages': lambda: pdf_bytes(tuple('a' for _ in range(101))),
    }[kind]()
    response = request(api_database.make_app(), 'POST', files={'file': ('private.pdf', source)})
    assert response.status_code == status and response.json()['error'] == code
    assert 'private' not in response.text and 'private' not in caplog.text
    assert row_count(api_database.engine) == 0
    with api_database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(DocumentPage)) == 0


def test_pdf_exact_original_byte_boundary(api_database):
    source = pdf_bytes()
    # Legal trailing PDF comment; no costly million-character metadata string.
    source += b'%' + b'x' * (1048576 - len(source) - 2) + b'\n'
    assert len(source) == 1048576
    app = api_database.make_app()
    assert request(app, 'POST', files={'file': ('exact.pdf', source)}).status_code == 201
    assert request(app, 'POST', files={'file': ('large.pdf', source + b' ')}).status_code == 413
    assert row_count(api_database.engine) == 1


@pytest.mark.parametrize('stage', ['pages', 'commit'])
def test_pdf_rollback_after_document_write(api_database, stage, caplog):
    app = api_database.make_app()
    visible = []
    def fail(connection, *args):
        if stage == 'pages' and not args[1].startswith('INSERT INTO document_pages'):
            return
        if stage == 'commit' and not connection.scalar(select(func.count()).select_from(Document)):
            return
        with api_database.make_engine().connect() as other:
            visible.append(other.scalar(select(func.count()).select_from(Document)))
        raise OperationalError('synthetic private SQL', {}, Exception('private data'))
    hook = 'before_cursor_execute' if stage == 'pages' else 'commit'
    event.listen(app.state.engine, hook, fail)
    try:
        result = request(app, 'POST', files={'file': ('synthetic.pdf', pdf_bytes())})
    finally:
        event.remove(app.state.engine, hook, fail)
    assert result.status_code == 503 and 'private' not in result.text and 'private' not in caplog.text
    assert visible == [0] and row_count(api_database.engine) == 0
    with api_database.engine.connect() as connection:
        assert connection.scalar(select(func.count()).select_from(DocumentPage)) == 0
    assert request(app, 'POST', files={'file': ('synthetic.pdf', pdf_bytes())}).status_code == 201


def test_pdf_ownership_duplicate_names_and_forged_owner(browsers):
    make, clock, database = browsers
    a, b = make(), make()
    a.account('a@example.com'); b.account('b@example.com')
    first = a.upload(pdf_bytes(), 'same.pdf').json()
    second = b.upload(pdf_bytes(('Other evidence.',)), 'same.pdf').json()
    assert first['id'] != second['id']
    assert a.client.get('/documents').json() == [first]
    assert b.client.get('/documents').json() == [second]
    assert a.post('/documents', files={'file': ('same.pdf', pdf_bytes())}, data={'owner_id': second['id']}).status_code == 400


@pytest.mark.parametrize('transition', ['logout', 'expiry'])
def test_session_change_during_extraction_prevents_storage(browsers, monkeypatch, transition):
    make, clock, database = browsers
    a = make(); a.account()
    original = pdf.extract_pdf
    def extract(data):
        pages = original(data)
        if transition == 'logout':
            assert a.post('/auth/logout').status_code == 204
        else:
            clock.advance(hours=9)
        return pages
    monkeypatch.setattr(pdf, 'extract_pdf', extract)
    assert a.upload(pdf_bytes(), 'source.pdf').status_code == 401
    assert row_count(database.engine) == 0


@pytest.mark.parametrize('declared', [None, '1', str(MAX_BODY_BYTES + 1)])
def test_streaming_body_cap_before_storage_and_closes_parser_files(api_database, monkeypatch, declared):
    import asyncio
    from tempfile import SpooledTemporaryFile
    from starlette import formparsers
    app = api_database.make_app()
    created = []
    def temporary(*args, **kwargs):
        stream = SpooledTemporaryFile(*args, **kwargs)
        created.append(stream)
        return stream
    monkeypatch.setattr(formparsers, 'SpooledTemporaryFile', temporary)
    raw, csrf = app.state.test_auth
    header = b'--test\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\n\r\n'
    chunks = [header] + [b'x' * 65536] * 33
    headers = [(b'content-type', b'multipart/form-data; boundary=test'), (b'cookie', ('dra_session=' + raw).encode()),
               (b'origin', b'http://127.0.0.1:8000'), (b'x-csrf-token', csrf.encode())]
    if declared:
        headers.append((b'content-length', declared.encode()))
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'http_version': '1.1', 'method': 'POST', 'path': '/documents',
             'raw_path': b'/documents', 'query_string': b'', 'headers': headers, 'scheme': 'http', 'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 1)}
    sent = []
    async def receive():
        return {'type': 'http.request', 'body': chunks.pop(0), 'more_body': bool(chunks)}
    async def send(message):
        sent.append(message)
    asyncio.run(app(scope, receive, send))
    assert sent[0]['status'] == 413
    assert all(stream.closed for stream in created)
    assert row_count(api_database.engine) == 0


def test_pdf_upgrade_preserves_owned_and_ownerless_txt_and_failed_revision_resumes(test_settings):
    with isolated_database(test_settings, '0002_auth') as database:
        from app.auth.models import User
        with database.engine.begin() as connection:
            user = connection.scalar(insert(User).values(email='synthetic@example.com', email_key='synthetic@example.com', password_hash='synthetic-not-used').returning(User.id))
            for owner in (None, user):
                connection.execute(text('INSERT INTO documents(original_filename,content,original_byte_size,owner_id) VALUES (:filename,:content,:size,:owner)'),
                                   {'filename': 'legacy.TXT', 'content': '  Café\r\n', 'size': len('  Café\r\n'.encode()), 'owner': owner})
            before = connection.execute(text('SELECT * FROM documents ORDER BY id')).mappings().all()
        def fail(connection, cursor, statement, *args):
            if statement.startswith('CREATE TABLE document_pages'):
                raise OperationalError('synthetic DDL failure', {}, Exception('synthetic'))
        # Alembic formats CREATE TABLE with a leading newline.
        def fail_ddl(connection, cursor, statement, *args):
            return fail(connection, cursor, statement.lstrip(), *args)
        event.listen(database.engine, 'before_cursor_execute', fail_ddl)
        with pytest.raises(OperationalError):
            migrate(database.engine, test_settings)
        event.remove(database.engine, 'before_cursor_execute', fail_ddl)
        with database.engine.connect() as connection:
            assert connection.scalar(text('SELECT version_num FROM alembic_version')) == '0002_auth'
            assert connection.execute(text('SELECT * FROM documents ORDER BY id')).mappings().all() == before
        migrate(database.engine, test_settings)
        with database.engine.connect() as connection:
            after = connection.execute(select(Document.__table__).order_by(Document.id)).mappings().all()
            assert [{k: row[k] for k in before[0]} for row in after] == before
            assert all(row['source_format'] == 'txt' and row['source_pdf'] is None for row in after)
            from scripts.check_schema import check_schema
            check_schema(connection, test_settings)
        with database.engine.begin() as connection:
            config = Config(str(BACKEND / 'alembic.ini'))
            config.attributes.update(connection=connection, settings=test_settings)
            command.check(config)
        with pytest.raises(RuntimeError, match='downgrade refused'):
            with database.engine.begin() as connection:
                config.attributes['connection'] = connection
                command.downgrade(config, '0002_auth')


def test_generated_page_status_and_source_constraints(api_database):
    app = api_database.make_app()
    assert request(app, 'POST', files={'file': ('source.pdf', pdf_bytes())}).status_code == 201
    with api_database.engine.begin() as connection:
        document_id = connection.scalar(select(Document.id))
        for change in [{'source_pdf': b'wrong length'}, {'page_count': 101}, {'source_format': 'other'}, {'extraction_version': None}]:
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(Document.__table__.update().where(Document.id == document_id).values(**change))
        for number, value in [(0, 'x'), (101, 'x'), (2, 'x' * 262145)]:
            with pytest.raises(IntegrityError):
                with connection.begin_nested():
                    connection.execute(insert(DocumentPage).values(document_id=document_id, page_number=number, text=value))
        connection.execute(insert(DocumentPage).values(document_id=document_id, page_number=2, text='\u2003\u00a0'))
        assert connection.scalar(select(DocumentPage.has_text).where(DocumentPage.page_number == 2)) is False
