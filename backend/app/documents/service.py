"""Synchronous transactional persistence with sanitized storage failures."""

from sqlalchemy import Engine, Integer, cast, func, insert, select
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.exc import SQLAlchemyError

from app.auth.service import check_csrf, require_session
from app.config import Settings
from app.db import assert_project_database
from app.documents.models import Document, DocumentPage
from app.documents.schemas import DocumentMetadata
from app.documents.validation import ValidatedDocument

METADATA_COLUMNS = (
    Document.id, Document.original_filename,
    Document.original_byte_size.label("byte_size"), Document.created_at, Document.source_format, Document.page_count,
)


class DocumentStorageError(Exception):
    """A storage operation failed; underlying details must not reach clients/logs."""


def save_document(engine: Engine, settings: Settings, document: ValidatedDocument, token_digest, csrf, clock) -> DocumentMetadata:
    if document.source_format == 'pdf':
        from app.documents.pdf import validate_pages, PROFILE
        if (validate_pages(list(document.pages)) != document.content or document.source_pdf is None
                or len(document.source_pdf) != document.byte_size or document.extraction_version != PROFILE):
            raise DocumentStorageError("Invalid extraction representation")
    elif document.source_format != 'txt' or document.pages or document.source_pdf is not None or document.extraction_version is not None:
        raise DocumentStorageError("Invalid document representation")
    try:
        with engine.begin() as connection:
            assert_project_database(connection, settings)
            identity = require_session(connection, token_digest, clock)
            check_csrf(identity, csrf)
            row = connection.execute(
                insert(Document).values(
                    owner_id=identity.user_id,
                    original_filename=document.original_filename,
                    content=document.content,
                    original_byte_size=document.byte_size,
                    source_format=document.source_format, source_pdf=document.source_pdf,
                    page_count=len(document.pages) if document.source_format == 'pdf' else None,
                    extraction_version=document.extraction_version,
                ).returning(*METADATA_COLUMNS)
            ).mappings().one()
            if document.pages:
                connection.execute(insert(DocumentPage), [dict(document_id=row['id'], page_number=i, text=page)
                                                         for i, page in enumerate(document.pages, 1)])
            metadata = DocumentMetadata.model_validate({**row, 'textless_pages': [i for i, page in enumerate(document.pages, 1) if not page or page.isspace()]})
        # Engine.begin commits on successful exit, rolls back on failure, and
        # returns the connection to the pool. Never return success before exit.
        return metadata
    except (SQLAlchemyError, RuntimeError):
        raise DocumentStorageError("Document storage is temporarily unavailable") from None


def list_documents(engine: Engine, settings: Settings, token_digest, clock) -> list[DocumentMetadata]:
    try:
        with engine.begin() as connection:
            assert_project_database(connection, settings)
            identity = require_session(connection, token_digest, clock)
            textless = select(func.array_agg(aggregate_order_by(DocumentPage.page_number, DocumentPage.page_number))).where(
                DocumentPage.document_id == Document.id, DocumentPage.has_text.is_(False)
            ).correlate(Document).scalar_subquery()
            rows = connection.execute(
                select(*METADATA_COLUMNS, func.coalesce(textless, cast([], ARRAY(Integer))).label('textless_pages')).where(owned_by(identity)).order_by(Document.created_at.asc(), Document.id.asc())
            ).mappings()
            return [DocumentMetadata.model_validate(row) for row in rows]
    except (SQLAlchemyError, RuntimeError):
        raise DocumentStorageError("Document storage is temporarily unavailable") from None


def owned_by(identity):
    """All account document queries use this explicit owner predicate."""
    if identity.user_id is None:
        raise ValueError("Authenticated owner required")
    return Document.owner_id == identity.user_id
