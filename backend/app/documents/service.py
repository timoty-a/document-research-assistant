"""Synchronous transactional persistence with sanitized storage failures."""

from sqlalchemy import Engine, insert, select
from sqlalchemy.exc import SQLAlchemyError

from app.auth.service import check_csrf, require_session
from app.config import Settings
from app.db import assert_project_database
from app.documents.models import Document
from app.documents.schemas import DocumentMetadata
from app.documents.validation import ValidatedDocument

METADATA_COLUMNS = (
    Document.id, Document.original_filename,
    Document.original_byte_size.label("byte_size"), Document.created_at,
)


class DocumentStorageError(Exception):
    """A storage operation failed; underlying details must not reach clients/logs."""


def save_document(engine: Engine, settings: Settings, document: ValidatedDocument, token_digest, csrf, clock) -> DocumentMetadata:
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
                ).returning(*METADATA_COLUMNS)
            ).mappings().one()
            metadata = DocumentMetadata.model_validate(row)
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
            rows = connection.execute(
                select(*METADATA_COLUMNS).where(owned_by(identity)).order_by(Document.created_at.asc(), Document.id.asc())
            ).mappings()
            return [DocumentMetadata.model_validate(row) for row in rows]
    except (SQLAlchemyError, RuntimeError):
        raise DocumentStorageError("Document storage is temporarily unavailable") from None


def owned_by(identity):
    """All account document queries use this explicit owner predicate."""
    if identity.user_id is None:
        raise ValueError("Authenticated owner required")
    return Document.owner_id == identity.user_id
