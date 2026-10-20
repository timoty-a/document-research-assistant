"""Initial document mapping and database invariants."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import Boolean, CheckConstraint, Computed, DateTime, ForeignKey, Index, Integer, LargeBinary, Text, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Python str.isspace() characters, including Unicode and control whitespace.
# Keep the initial migration independent of this mutable model definition.
NONBLANK_CONTENT = (
    "length(btrim(content, U&'\\0009\\000A\\000B\\000C\\000D"
    "\\001C\\001D\\001E\\001F\\0020\\0085\\00A0\\1680"
    "\\2000\\2001\\2002\\2003\\2004\\2005\\2006\\2007"
    "\\2008\\2009\\200A\\2028\\2029\\202F\\205F\\3000')) > 0"
)


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_owner_created_id", "owner_id", "created_at", "id"),
        CheckConstraint("length(original_filename) > 0", name="ck_documents_filename_nonempty"),
        CheckConstraint("(source_format = 'txt' AND lower(right(original_filename, 4)) = '.txt') OR (source_format = 'pdf' AND lower(right(original_filename, 4)) = '.pdf')", name="ck_documents_format_extension"),
        CheckConstraint("original_byte_size BETWEEN 1 AND 1048576", name="ck_documents_byte_size"),
        CheckConstraint(NONBLANK_CONTENT, name="ck_documents_content_nonblank"),
        CheckConstraint(
            "source_format != 'txt' OR octet_length(convert_to(content, 'UTF8')) = original_byte_size",
            name="ck_documents_utf8_byte_size",
        ),
        CheckConstraint("octet_length(convert_to(content, 'UTF8')) <= 2097152", name="ck_documents_text_limit"),
        CheckConstraint("(source_format = 'txt' AND source_pdf IS NULL AND page_count IS NULL AND extraction_version IS NULL) OR (source_format = 'pdf' AND source_pdf IS NOT NULL AND octet_length(source_pdf) = original_byte_size AND page_count IS NOT NULL AND page_count BETWEEN 1 AND 100 AND extraction_version IS NOT NULL AND length(extraction_version) BETWEEN 1 AND 100)", name="ck_documents_source"),
    )

    source_format: Mapped[str] = mapped_column(Text, nullable=False, server_default=text("'txt'"))
    source_pdf: Mapped[bytes | None] = mapped_column(LargeBinary)
    page_count: Mapped[int | None] = mapped_column(Integer)
    extraction_version: Mapped[str | None] = mapped_column(Text)

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", name="fk_documents_owner", ondelete="RESTRICT"))


# Match PostgreSQL's reflected literal/cast form so Alembic can compare the
# generated expression without a false positive about changing a computed value.
PAGE_WHITESPACE = ''.join(chr(code) for code in [9, 10, 11, 12, 13, 28, 29, 30, 31, 32, 133, 160, 5760, *range(8192, 8203), 8232, 8233, 8239, 8287, 12288])
PAGE_NONBLANK = "length(btrim(text, '" + PAGE_WHITESPACE + "'::text)) > 0"


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (
        CheckConstraint("page_number BETWEEN 1 AND 100", name="ck_pages_number"),
        CheckConstraint("octet_length(convert_to(text, 'UTF8')) <= 262144", name="ck_pages_text_limit"),
    )
    document_id: Mapped[UUID] = mapped_column(ForeignKey("documents.id", name="fk_pages_document", ondelete="CASCADE"), primary_key=True)
    page_number: Mapped[int] = mapped_column(Integer, primary_key=True)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    has_text: Mapped[bool] = mapped_column(Boolean, Computed(PAGE_NONBLANK, persisted=True), nullable=False)
