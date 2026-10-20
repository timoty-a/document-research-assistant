"""Deterministic bounded lexical search; saved text/offsets are never normalized."""
from collections import Counter
from dataclasses import dataclass, field
import re
import unicodedata
from uuid import UUID

CHUNK_SIZE = 1000
OVERLAP = 160
MAX_CHUNKS = 15000
MAX_SOURCE_BYTES = 10 * 1024 * 1024
MAX_EVIDENCE = 6
STOPWORDS = frozenset('a an and are as at be by can do does for from how i in is it of on or that the their these this to was were what when where which who why with would about say says document documents report reports'.split())


@dataclass(frozen=True)
class Source:
    document_id: UUID
    original_filename: str = field(repr=False)
    source_format: str
    page_number: int | None
    extraction_version: str
    text: str = field(repr=False)


@dataclass(frozen=True)
class Evidence:
    source: Source = field(repr=False)
    start: int
    end: int
    quote: str = field(repr=False)


def terms(text):
    normalized = unicodedata.normalize('NFKC', text).casefold()
    return [token for token in re.findall(r'[^\W_]+', normalized) if 2 <= len(token) <= 64 and token not in STOPWORDS]


def windows(text):
    start = 0
    while start < len(text):
        end = min(start + CHUNK_SIZE, len(text))
        if end < len(text):
            # Prefer a nearby whitespace boundary, retaining the exact slice.
            boundary = max(text.rfind('\n', start + CHUNK_SIZE * 3 // 4, end),
                           text.rfind(' ', start + CHUNK_SIZE * 3 // 4, end))
            if boundary > start:
                end = boundary + 1
        yield start, end, text[start:end]
        if end == len(text):
            break
        start = max(start + 1, end - OVERLAP)


def retrieve(question, sources):
    query = set(terms(question)[:20])
    if not query:
        return []
    candidates = []
    chunks = 0
    for order, source in enumerate(sources):
        for start, end, quote in windows(source.text):
            chunks += 1
            if chunks > MAX_CHUNKS:
                raise ValueError('Selection exceeds retrieval budget')
            frequencies = Counter(terms(quote))
            matches = query & frequencies.keys()
            if matches:
                # Coverage first, then bounded frequency; no entailment claim.
                key = (-len(matches), -sum(min(3, frequencies[word]) for word in matches), order, start)
                candidates.append((key, Evidence(source, start, end, quote)))
    ranked = sorted(candidates, key=lambda item: item[0])
    chosen = []
    seen_documents = set()
    def add(candidate):
        for old in chosen:
            if (old.source.document_id, old.source.page_number) == (candidate.source.document_id, candidate.source.page_number):
                intersection = max(0, min(old.end, candidate.end) - max(old.start, candidate.start))
                if intersection >= min(old.end - old.start, candidate.end - candidate.start) / 2:
                    return
        chosen.append(candidate)
        seen_documents.add(candidate.source.document_id)
    # Give each matching source a chance before filling the remaining slots.
    for _, candidate in ranked:
        if candidate.source.document_id not in seen_documents:
            add(candidate)
        if len(chosen) == MAX_EVIDENCE:
            return chosen
    for _, candidate in ranked:
        if candidate not in chosen:
            add(candidate)
        if len(chosen) == MAX_EVIDENCE:
            break
    return chosen
