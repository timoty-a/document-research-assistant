"""Real ownership/session/database checks; AI synthesis is explicitly mocked."""
import asyncio
import json
from uuid import uuid4

from pydantic import SecretStr
import pytest
from sqlalchemy import event, insert
from sqlalchemy.exc import OperationalError

from app.documents.models import Document
from app.research import service
from app.research.provider import ResearchError
from pdf_samples import pdf_bytes

pytestmark = pytest.mark.database


def setup(make, *, enabled=False):
    browser = make(); browser.account()
    calls = []
    browser.app.state.settings = browser.app.state.settings.model_copy(update={'ai_enabled': enabled, 'groq_api_key': SecretStr('synthetic-key') if enabled else None})
    def generate(question, evidence, settings):
        calls.append((question, evidence))
        return {'status': 'answered', 'claims': [{'text': 'Solar costs fell in the supplied evidence.', 'citation_ids': ['E1']}]}
    browser.app.state.research_generator = generate
    return browser, calls


def ask(browser, ids, question='What happened to solar costs?', endpoint='questions', **kwargs):
    return browser.post('/research/' + endpoint, json={'question': question, 'document_ids': ids}, **kwargs)


def inspect(browser, citation, **changes):
    params = {'start': citation['start'], 'end': citation['end'], 'page': citation['page_number'] or 0, 'version': citation['extraction_version'], **changes}
    return browser.client.get('/documents/' + citation['document_id'] + '/passage', params=params)


def test_search_is_local_and_quotes_have_exact_unicode_context(browsers):
    make, clock, database = browsers
    a, calls = setup(make)
    original = '😀  Solar costs fell by ten percent.\r\n'
    doc = a.upload(original.encode(), 'synthetic.txt').json()
    result = ask(a, [doc['id']], endpoint='search')
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    assert result.headers['x-session-context']
    body = result.json()
    assert body['status'] == 'evidence_only' and body['claims'] == [] and not calls
    citation = body['citations'][0]
    assert citation['quote'] == original[citation['start']:citation['end']] == original
    passage = inspect(a, citation)
    assert passage.status_code == 200
    assert passage.json()['quote'] == original and passage.json()['page_number'] is None
    assert passage.headers['x-session-context'] == result.headers['x-session-context']


def test_mocked_synthesis_resolves_source_names_and_physical_pages(browsers):
    make, clock, database = browsers
    a, calls = setup(make, enabled=True)
    doc = a.upload(pdf_bytes((None, 'Solar costs fell.')), 'same.PDF').json()
    result = ask(a, [doc['id']])
    assert result.status_code == 200
    body = result.json()
    assert body['status'] == 'answered' and len(calls) == 1
    assert body['claims'][0]['citation_ids'] == ['E1']
    c = body['citations'][0]
    assert c['original_filename'] == 'same.PDF' and c['page_number'] == 2 and c['quote'] == 'Solar costs fell.'
    assert inspect(a, c).json()['quote'] == c['quote']
    assert any('no extracted text' in warning for warning in body['warnings'])


def test_disabled_provider_and_no_match_never_call_adapter(browsers):
    make, clock, database = browsers
    a, calls = setup(make)
    doc = a.upload(b'Solar costs fell.').json()
    assert a.client.get('/research/status').json() == {'enabled': False, 'provider': None, 'model': None}
    assert ask(a, [doc['id']]).status_code == 503
    empty = ask(a, [doc['id']], 'unrelatedxyz')
    assert empty.status_code == 200 and empty.json()['status'] == 'no_evidence' and not calls


def test_all_selected_ids_must_be_owned_and_ownerless_stays_private(browsers):
    make, clock, database = browsers
    a, calls = setup(make, enabled=True)
    b = make(); b.account('other@example.com')
    own = a.upload(b'Solar costs fell.', 'same.txt').json()
    other = b.upload(b'Solar costs rose.', 'same.txt').json()
    with database.engine.begin() as connection:
        legacy = connection.scalar(insert(Document).values(original_filename='legacy.txt', content='solar', original_byte_size=5).returning(Document.id))
    for hidden in [other['id'], str(legacy), str(uuid4())]:
        result = ask(a, [own['id'], hidden])
        assert result.status_code == 404 and result.json()['error'] == 'source_unavailable'
        assert inspect(a, {'document_id': hidden, 'start': 0, 'end': 1, 'page_number': None, 'extraction_version': 'txt:utf8-v1'}).status_code == 404
    assert not calls
    result = ask(b, [other['id']], endpoint='search')
    assert result.status_code == 200 and all(c['document_id'] == other['id'] for c in result.json()['citations'])


@pytest.mark.parametrize('change,status', [
    ({'page': 2}, 404), ({'start': -1}, 422), ({'end': 99999}, 400), ({'version': 'changed'}, 409),
])
def test_passage_ranges_and_version_are_validated(browsers, change, status):
    make, clock, database = browsers
    a, _ = setup(make)
    doc = a.upload(b'Solar costs fell.').json()
    citation = ask(a, [doc['id']], endpoint='search').json()['citations'][0]
    assert inspect(a, citation, **change).status_code == status


@pytest.mark.parametrize('payload', [
    {'question': '', 'document_ids': []}, {'question': ' '},
    {'question': 'x' * 1001, 'document_ids': []},
    {'question': 'private\x00input', 'document_ids': [str(uuid4())]},
    {'question': 'solar', 'document_ids': [str(uuid4())] * 2},
    {'question': 'solar', 'document_ids': [str(uuid4()) for _ in range(6)]},
    {'question': 'solar', 'document_ids': ['not-an-id'], 'owner_id': 'private'},
])
def test_bounded_validation_never_echoes_inputs(browsers, payload):
    make, clock, database = browsers
    a, calls = setup(make)
    result = a.post('/research/search', json=payload)
    assert result.status_code == 422 and 'private' not in result.text and not calls


def test_json_media_size_origin_and_csrf_limits(browsers):
    make, clock, database = browsers
    a, calls = setup(make)
    assert a.post('/research/search', content=b'x' * 8193, headers={'Content-Type': 'application/json'}).status_code == 413
    assert a.post('/research/search', content=b'solar', headers={'Content-Type': 'text/plain'}).status_code == 415
    assert a.post('/research/search', json={}, headers={'Origin': 'https://evil.example'}).status_code == 403
    assert a.post('/research/search', json={}, headers={'X-CSRF-Token': 'wrong'}).status_code == 403
    assert not calls


@pytest.mark.parametrize('path,method', [('/research/questions', 'POST'), ('/research/search', 'POST'), ('/research/status', 'GET'), ('/documents/' + str(uuid4()) + '/passage', 'GET')])
def test_unauthorized_new_routes_reject_before_body_receipt(auth_database, path, method):
    app = auth_database.make_app()
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': method, 'path': path, 'raw_path': path.encode(),
             'query_string': b'', 'headers': [(b'content-type', b'application/json')], 'scheme': 'http',
             'http_version': '1.1', 'server': ('127.0.0.1', 8000), 'client': ('127.0.0.1', 1)}
    sent = []
    async def receive(): pytest.fail('Unauthenticated research must not read a body')
    async def send(message): sent.append(message)
    asyncio.run(app(scope, receive, send))
    assert sent[0]['status'] == 401


@pytest.mark.parametrize('transition', ['logout', 'expiry'])
def test_session_change_during_model_call_discards_answer(browsers, transition):
    make, clock, database = browsers
    a, calls = setup(make, enabled=True)
    doc = a.upload(b'Solar costs fell.').json()
    def generate(*args):
        if transition == 'logout': assert a.post('/auth/logout').status_code == 204
        else: clock.advance(hours=9)
        return {'status': 'answered', 'claims': [{'text': 'Old private answer', 'citation_ids': ['E1']}]}
    a.app.state.research_generator = generate
    result = ask(a, [doc['id']])
    assert result.status_code == 401 and 'Old private' not in result.text


@pytest.mark.parametrize('fault', ['unknown-citation', 'exception', 'store'])
def test_failures_are_sanitized_and_resources_release(browsers, fault, caplog):
    make, clock, database = browsers
    a, calls = setup(make, enabled=True)
    doc = a.upload(b'Solar costs fell.').json()
    def generate(*args):
        if fault == 'exception': raise RuntimeError('private question / key / SQL')
        return {'status': 'answered', 'claims': [{'text': 'Unsupported', 'citation_ids': ['E99']}]}
    a.app.state.research_generator = generate
    def fail(connection, cursor, statement, *args):
        if 'FROM documents' in statement: raise OperationalError('private SQL', {}, Exception('private'))
    if fault == 'store': event.listen(a.app.state.engine, 'before_cursor_execute', fail)
    try:
        result = ask(a, [doc['id']])
    finally:
        if fault == 'store': event.remove(a.app.state.engine, 'before_cursor_execute', fail)
    assert result.status_code in {502, 503} and 'private' not in result.text and 'private' not in caplog.text
    assert service._SLOT.acquire(False)
    service._SLOT.release()


def test_persisted_provider_budget_and_concurrency_gate(browsers):
    make, clock, database = browsers
    a, calls = setup(make, enabled=True)
    doc = a.upload(b'Solar costs fell.').json()
    for _ in range(6): assert ask(a, [doc['id']]).status_code == 200
    assert ask(a, [doc['id']]).status_code == 429 and len(calls) == 6
    clock.advance(minutes=1)
    assert ask(a, [doc['id']]).status_code == 200
    assert service._SLOT.acquire(False) and service._SLOT.acquire(False)
    try:
        assert ask(a, [doc['id']]).status_code == 429
    finally:
        service._SLOT.release(); service._SLOT.release()
