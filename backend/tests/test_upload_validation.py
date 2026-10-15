from io import BytesIO

import pytest
from fastapi import HTTPException, UploadFile

from app.documents import validation


class CountedStream(BytesIO):
    def __init__(self, data):
        super().__init__(data)
        self.bytes_read = 0
        self.read_sizes = []

    def read(self, size=-1):
        assert 0 < size <= validation.READ_CHUNK_BYTES
        self.read_sizes.append(size)
        chunk = super().read(size)
        self.bytes_read += len(chunk)
        return chunk


def test_reads_only_limit_plus_sentinel_and_ignores_declared_size():
    stream = CountedStream(b"x" * (validation.MAX_DOCUMENT_BYTES + 5000))
    upload = UploadFile(stream, filename="synthetic.txt", size=1)
    with pytest.raises(HTTPException) as error:
        validation.read_document(upload)
    assert error.value.status_code == 413
    assert stream.bytes_read == validation.MAX_DOCUMENT_BYTES + 1
    assert stream.closed


def test_valid_content_ignores_overstated_size_and_closes_file():
    stream = CountedStream("  héllo\r\n".encode())
    upload = UploadFile(stream, filename="../synthetic.TXT", size=999999999)
    document = validation.read_document(upload)
    assert document.content == "  héllo\r\n"
    assert document.original_filename == "../synthetic.TXT"
    assert document.byte_size == len("  héllo\r\n".encode())
    assert stream.closed
    assert "héllo" not in repr(document)


@pytest.mark.parametrize("filename", [None, "", "bad\x00.txt", "bad\ud800.txt", "wrong.pdf"])
def test_invalid_filename_closes_stream_without_reading(filename):
    stream = CountedStream(b"synthetic")
    with pytest.raises(HTTPException) as error:
        validation.read_document(UploadFile(stream, filename=filename))
    assert error.value.status_code == 400
    assert stream.bytes_read == 0
    assert stream.closed


def test_filename_text_storage_limit_counts_utf8_bytes(monkeypatch):
    # Exercise the storage-bound branch without allocating a 1 GiB header.
    monkeypatch.setattr(validation, "MAX_FILENAME_BYTES", 8)
    assert validation.validate_filename("éé.TXT") == "éé.TXT"
    with pytest.raises(HTTPException) as error:
        validation.validate_filename("ééé.txt")
    assert error.value.status_code == 400


@pytest.mark.parametrize("data", [b"", b" \t\r\n", b"\xff", b"ok\x00"])
def test_invalid_content_closes_stream(data):
    stream = CountedStream(data)
    with pytest.raises(HTTPException) as error:
        validation.read_document(UploadFile(stream, filename="synthetic.txt"))
    assert error.value.status_code == 400
    assert stream.closed
