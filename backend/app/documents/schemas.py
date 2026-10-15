"""Public document metadata; content is intentionally absent."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class DocumentMetadata(BaseModel):
    id: UUID
    original_filename: str
    byte_size: int
    created_at: datetime
