from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Question(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    question: str = Field(min_length=1, max_length=1000)
    document_ids: list[UUID] = Field(min_length=1, max_length=5)

    @field_validator('question')
    @classmethod
    def usable_question(cls, value):
        if not value.strip() or '\x00' in value:
            raise ValueError('Invalid question')
        value.encode('utf-8', errors='strict')
        return value

    @field_validator('document_ids')
    @classmethod
    def distinct_sources(cls, value):
        if len(set(value)) != len(value):
            raise ValueError('Duplicate sources')
        return value


class Citation(BaseModel):
    id: str
    document_id: UUID
    original_filename: str
    source_format: Literal['txt', 'pdf']
    page_number: int | None
    extraction_version: str
    start: int
    end: int
    quote: str


class Claim(BaseModel):
    text: str
    citation_ids: list[str]


class Answer(BaseModel):
    status: Literal['answered', 'insufficient_evidence', 'no_evidence', 'evidence_only']
    question: str
    claims: list[Claim]
    citations: list[Citation]
    warnings: list[str]


class Passage(BaseModel):
    document_id: UUID
    original_filename: str
    source_format: Literal['txt', 'pdf']
    page_number: int | None
    extraction_version: str
    start: int
    end: int
    before: str
    quote: str
    after: str
