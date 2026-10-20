"""Owner-filtered retrieval and rechecked session boundaries around generation."""
import threading

from sqlalchemy import case, select

from app.auth import service as auth
from app.documents.models import Document, DocumentPage
from app.documents.service import owned_by
from app.research.provider import ResearchError, generate, validate_answer
from app.research.retrieval import Evidence, Source, MAX_SOURCE_BYTES, retrieve
from app.research.schemas import Answer, Citation, Claim, Passage

_SLOT = threading.BoundedSemaphore(2)
NOTICE = 'Citations locate saved text; they do not prove the answer is correct. Check each claim against its evidence.'


def missing():
    return ResearchError(404, 'source_unavailable', 'One or more selected sources or passages are unavailable.')


def selected_rows(connection, identity, document_ids):
    rows = connection.execute(select(Document.id, Document.original_filename, Document.source_format,
        Document.extraction_version, Document.page_count,
        case((Document.source_format == 'txt', Document.content), else_=None).label('text')
    ).where(owned_by(identity), Document.id.in_(document_ids)).order_by(Document.created_at, Document.id)).mappings().all()
    if len(rows) != len(document_ids):
        raise missing()
    return rows


def load_sources(engine, settings, token, csrf, clock, document_ids):
    with auth.transaction(engine, settings) as connection:
        identity = auth.require_session(connection, token, clock)
        auth.check_csrf(identity, csrf)
        rows = selected_rows(connection, identity, document_ids)
        sources = []
        total = 0
        def add(row, page, text):
            nonlocal total
            total += len(text.encode('utf-8'))
            if total > MAX_SOURCE_BYTES:
                raise ResearchError(413, 'research_limit', 'Selected sources exceed the local search limit. Select fewer documents.')
            sources.append(Source(row['id'], row['original_filename'], row['source_format'], page,
                                  row['extraction_version'] or 'txt:utf8-v1', text))
        for row in rows:
            if row['source_format'] == 'txt':
                add(row, None, row['text'])
            else:
                pages = connection.execute(select(DocumentPage.page_number, DocumentPage.text).join(
                    Document, Document.id == DocumentPage.document_id).where(
                    owned_by(identity), Document.id == row['id']).order_by(DocumentPage.page_number)
                ).yield_per(10)
                for page in pages:
                    add(row, page.page_number, page.text)
        return sources, identity.user_id


def recheck(engine, settings, token, csrf, clock, document_ids):
    with auth.transaction(engine, settings) as connection:
        identity = auth.require_session(connection, token, clock)
        auth.check_csrf(identity, csrf)
        owned = set(connection.scalars(select(Document.id).where(owned_by(identity), Document.id.in_(document_ids))))
        if owned != set(document_ids):
            raise missing()


def citation(item, number):
    return Citation(id=f'E{number}', document_id=item.source.document_id, original_filename=item.source.original_filename,
                    source_format=item.source.source_format, page_number=item.source.page_number,
                    extraction_version=item.source.extraction_version, start=item.start, end=item.end, quote=item.quote)


def answer(engine, settings, token, csrf, clock, question, *, synthesize=False, generator=generate):
    if not _SLOT.acquire(False):
        raise ResearchError(429, 'research_busy', 'Research is busy. Wait before trying again.')
    try:
        sources, user_id = load_sources(engine, settings, token, csrf, clock, question.document_ids)
        try:
            evidence = retrieve(question.question, sources)
        except ValueError:
            raise ResearchError(413, 'research_limit', 'Selection exceeds the local search limit. Select fewer sources.') from None
        warnings = [NOTICE]
        if any(source.source_format == 'pdf' for source in sources):
            warnings.append('PDF images are not read. Page order is physical PDF order; extracted text and existing OCR may contain errors.')
        if any(source.source_format == 'pdf' and not source.text.strip() for source in sources):
            warnings.append('Some PDF pages have no extracted text and cannot supply evidence.')
        if evidence and len({item.source.document_id for item in evidence}) < len(question.document_ids):
            warnings.append('No matching passages were found in some selected sources; the evidence does not cover every selected document.')
        citations = [citation(item, index) for index, item in enumerate(evidence, 1)]
        status = 'evidence_only' if evidence else 'no_evidence'
        claims = []
        if synthesize and evidence:
            if not settings.ai_enabled:
                raise ResearchError(503, 'ai_not_configured', 'AI answering is not enabled. You can still search passages locally.')
            auth.throttle(engine, settings, [('research_minute', str(user_id), 6, 60),
                                            ('research_day', str(user_id), 20, 86400),
                                            ('research_project_day', 'local', 100, 86400)], clock)
            recheck(engine, settings, token, csrf, clock, question.document_ids)
            try:
                generated = generator(question.question, evidence, settings)
            except ResearchError:
                raise
            except Exception:
                raise ResearchError(503, 'provider_unavailable', 'The AI answer could not be confirmed. No automatic retry was made.') from None
            # Validate even injectable adapters: provenance is enforced here too.
            generated = validate_answer(generated.model_dump() if hasattr(generated, 'model_dump') else generated, len(evidence))
            status = generated.status
            claims = [Claim(text=claim.text, citation_ids=claim.citation_ids) for claim in generated.claims]
        recheck(engine, settings, token, csrf, clock, question.document_ids)
        return Answer(status=status, question=question.question, claims=claims, citations=citations, warnings=warnings)
    finally:
        _SLOT.release()


def passage(engine, settings, token, clock, document_id, page, start, end, version):
    with auth.transaction(engine, settings) as connection:
        identity = auth.require_session(connection, token, clock)
        row = selected_rows(connection, identity, [document_id])[0]
        actual_version = row['extraction_version'] or 'txt:utf8-v1'
        if actual_version != version:
            raise ResearchError(409, 'source_changed', 'The saved extraction changed. Ask the question again to refresh its citations.')
        if row['source_format'] == 'txt':
            if page != 0:
                raise missing()
            content = row['text']
        else:
            content = connection.scalar(select(DocumentPage.text).join(Document, Document.id == DocumentPage.document_id).where(
                owned_by(identity), Document.id == document_id, DocumentPage.page_number == page))
            if content is None:
                raise missing()
        if not 0 <= start < end <= len(content) or end - start > 1000:
            raise ResearchError(400, 'invalid_range', 'The requested passage range is invalid.')
        return Passage(document_id=document_id, original_filename=row['original_filename'], source_format=row['source_format'],
                       page_number=page or None, extraction_version=actual_version, start=start, end=end,
                       before=content[max(0, start - 200):start], quote=content[start:end], after=content[end:end + 200])
