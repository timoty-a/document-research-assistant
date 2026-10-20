"""Bounded PDF process orchestration and validation of its untrusted output."""
import json
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
from importlib.metadata import version

from app.documents.pdf_worker import MAX_OUTPUT_BYTES, MAX_PAGES, MAX_PAGE_BYTES, MAX_TEXT_BYTES, SEPARATOR

PROFILE = f'pypdf:{version("pypdf")}:plain-v1'
WALL_SECONDS = 10
_SLOT = threading.BoundedSemaphore(1)
WORKER = Path(__file__).with_name('pdf_worker.py')
ERRORS = {
    'pdf_encrypted': (400, 'Encrypted PDFs are not supported. Export an unencrypted copy.'),
    'pdf_no_text': (400, 'No usable text could be extracted. Scanned PDFs without a text layer need OCR, which is not supported.'),
    'pdf_invalid': (400, 'PDF could not be read safely. Export a valid, unencrypted text-based PDF.'),
    'pdf_limit_exceeded': (413, 'PDF exceeds the page, extracted-text, or processing limits.'),
    'pdf_unavailable': (503, 'PDF processing is temporarily unavailable.'),
    'pdf_busy': (429, 'PDF processing is busy. Wait before trying again.'),
}


class PDFError(Exception):
    def __init__(self, code):
        self.code = code if code in ERRORS else 'pdf_unavailable'
        self.status, self.detail = ERRORS[self.code]
        super().__init__(self.code)


def validate_pages(pages):
    if not isinstance(pages, list) or not pages or len(pages) > MAX_PAGES:
        raise PDFError('pdf_invalid')
    if any(not isinstance(page, str) or '\x00' in page for page in pages):
        raise PDFError('pdf_invalid')
    try:
        if any(len(page.encode('utf-8')) > MAX_PAGE_BYTES for page in pages):
            raise PDFError('pdf_limit_exceeded')
        content = SEPARATOR.join(pages)
        if len(content.encode('utf-8')) > MAX_TEXT_BYTES:
            raise PDFError('pdf_limit_exceeded')
    except UnicodeError:
        raise PDFError('pdf_invalid') from None
    if not any(page and not page.isspace() for page in pages):
        raise PDFError('pdf_no_text')
    return content


def run_worker(data):
    # Files avoid pipe deadlocks and unbounded communicate() output accumulation.
    # TemporaryFile uses private/unnamed storage and never uses the supplied name.
    with tempfile.TemporaryFile() as source, tempfile.TemporaryFile() as output:
        source.write(data)
        source.seek(0)
        process = None
        try:
            process = subprocess.Popen(
                [sys.executable, '-I', str(WORKER)], stdin=source, stdout=output,
                stderr=subprocess.DEVNULL, env={'LANG': 'C.UTF-8'},
                cwd=WORKER.parent, close_fds=True,
            )
            try:
                code = process.wait(timeout=WALL_SECONDS)
            except subprocess.TimeoutExpired:
                raise PDFError('pdf_limit_exceeded') from None
            if code < 0 and -code in {signal.SIGXCPU, signal.SIGXFSZ}:
                raise PDFError('pdf_limit_exceeded')
            if code != 0:
                raise PDFError('pdf_unavailable')
            output.seek(0)
            payload = output.read(MAX_OUTPUT_BYTES + 1)
            if len(payload) > MAX_OUTPUT_BYTES:
                raise PDFError('pdf_limit_exceeded')
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise PDFError('pdf_unavailable')
            if set(result) == {'error'} and isinstance(result['error'], str):
                raise PDFError(result['error'])
            if set(result) != {'pages'}:
                raise PDFError('pdf_unavailable')
            validate_pages(result['pages'])
            return tuple(result['pages'])
        except (OSError, ValueError, UnicodeError):
            raise PDFError('pdf_unavailable') from None
        finally:
            if process is not None:
                if process.poll() is None:
                    process.kill()
                process.wait()


def extract_pdf(data):
    if not data.startswith(b'%PDF-'):
        raise PDFError('pdf_invalid')
    if not _SLOT.acquire(blocking=False):
        raise PDFError('pdf_busy')
    try:
        return run_worker(data)
    finally:
        _SLOT.release()
