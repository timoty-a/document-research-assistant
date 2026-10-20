"""Public document metadata; content is intentionally absent."""

from datetime import datetime
from uuid import UUID

from typing import Literal

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    id: UUID
    original_filename: str
    byte_size: int
    created_at: datetime
    source_format: Literal["txt", "pdf"] = "txt"
    page_count: int | None = None
    textless_pages: list[int] = Field(default_factory=list)
