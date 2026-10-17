"""Initial document mapping and database invariants."""

from datetime import datetime
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, Text, func, text
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
        CheckConstraint("lower(right(original_filename, 4)) = '.txt'", name="ck_documents_txt_extension"),
        CheckConstraint("original_byte_size BETWEEN 1 AND 1048576", name="ck_documents_byte_size"),
        CheckConstraint(NONBLANK_CONTENT, name="ck_documents_content_nonblank"),
        CheckConstraint(
            "octet_length(convert_to(content, 'UTF8')) = original_byte_size",
            name="ck_documents_utf8_byte_size",
        ),
    )

    id: Mapped[UUID] = mapped_column(primary_key=True, server_default=text("gen_random_uuid()"))
    original_filename: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    original_byte_size: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    owner_id: Mapped[UUID | None] = mapped_column(ForeignKey("users.id", name="fk_documents_owner", ondelete="RESTRICT"))
