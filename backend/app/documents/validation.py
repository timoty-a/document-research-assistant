"""Bounded reads and validation of untrusted document data."""

from dataclasses import dataclass, field

from fastapi import HTTPException, UploadFile

MAX_DOCUMENT_BYTES = 1_048_576
READ_CHUNK_BYTES = 65_536
# PostgreSQL TEXT has no declared character limit here. MaxAllocSize is
# 1 GiB - 1; reserve the four-byte variable-length value header.
MAX_FILENAME_BYTES = (1 << 30) - 5


@dataclass(frozen=True)
class ValidatedDocument:
    original_filename: str = field(repr=False)
    content: str = field(repr=False)
    byte_size: int


def validate_filename(filename: str | None) -> str:
    if not filename or "\x00" in filename:
        raise HTTPException(400, "A non-empty filename without null characters is required")
    encoded_size = 0
    try:
        for offset in range(0, len(filename), READ_CHUNK_BYTES):
            encoded_size += len(filename[offset:offset + READ_CHUNK_BYTES].encode("utf-8", errors="strict"))
            if encoded_size > MAX_FILENAME_BYTES:
                raise HTTPException(400, "Filename exceeds the database text storage limit")
    except UnicodeError:
        raise HTTPException(400, "Filename must be valid UTF-8 text") from None
    if filename[-4:].lower() != ".txt":
        raise HTTPException(400, "Only .txt files are supported")
    # No path operations: even a path-looking filename is just metadata.
    return filename


def read_document(upload: UploadFile) -> ValidatedDocument:
    """Read at most the limit plus one sentinel byte; ignore declared sizes."""
    try:
        filename = validate_filename(upload.filename)
        data = bytearray()
        while True:
            chunk = upload.file.read(min(READ_CHUNK_BYTES, MAX_DOCUMENT_BYTES + 1 - len(data)))
            if not chunk:
                break
            data.extend(chunk)
            if len(data) > MAX_DOCUMENT_BYTES:
                raise HTTPException(413, "File exceeds the 1,048,576-byte limit")
        try:
            content = data.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise HTTPException(400, "File must contain valid UTF-8 text") from None
        if "\x00" in content:
            raise HTTPException(400, "Text must not contain null characters")
        if not content or content.isspace():
            raise HTTPException(400, "File must contain non-whitespace text")
        return ValidatedDocument(filename, content, len(data))
    finally:
        upload.file.close()
