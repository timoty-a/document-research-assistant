"""Minimal isolated-process entry point: no app/config/DB imports or credentials."""
import io
import json
import logging
import sys
import warnings

MAX_PAGES = 100
MAX_PAGE_BYTES = 262_144
MAX_TEXT_BYTES = 2_097_152
MAX_SOURCE_BYTES = 1_048_576
MAX_OUTPUT_BYTES = 4_194_304
MEMORY_BYTES = 512 * 1024 * 1024
CPU_SECONDS = 5
SEPARATOR = '\n\f\n'


def apply_limits():
    import resource
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BYTES, MEMORY_BYTES))
    resource.setrlimit(resource.RLIMIT_CPU, (CPU_SECONDS, CPU_SECONDS + 1))
    resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT_BYTES, MAX_OUTPUT_BYTES))


def extract(data):
    from pypdf import PdfReader
    class EncryptedInput(Exception):
        pass

    class UnencryptedReader(PdfReader):
        # Pinned pypdf constructor attempts an empty password before it returns.
        # Stop at this hook, before crypto/password verification, including AES
        # inputs without the optional crypto package. Covered by a contract test.
        def _handle_encryption(self, password):
            raise EncryptedInput()

    try:
        reader = UnencryptedReader(io.BytesIO(data), strict=True)
    except EncryptedInput:
        return {'error': 'pdf_encrypted'}
    count = len(reader.pages)
    if count > MAX_PAGES:
        return {'error': 'pdf_limit_exceeded'}
    if count == 0:
        return {'error': 'pdf_no_text'}
    pages = []
    total = 0
    for page in reader.pages:
        text = page.extract_text(extraction_mode='plain')
        size = len(text.encode('utf-8', errors='strict'))
        if '\x00' in text:
            return {'error': 'pdf_invalid'}
        total += size + (len(SEPARATOR) if pages else 0)
        if size > MAX_PAGE_BYTES or total > MAX_TEXT_BYTES:
            return {'error': 'pdf_limit_exceeded'}
        pages.append(text)
    if not any(text and not text.isspace() for text in pages):
        return {'error': 'pdf_no_text'}
    return {'pages': pages}


def main():
    logging.disable(logging.CRITICAL)
    warnings.simplefilter('ignore')
    try:
        apply_limits()
    except Exception:
        result = {'error': 'pdf_unavailable'}
    else:
        try:
            data = sys.stdin.buffer.read(MAX_SOURCE_BYTES + 1)
            if len(data) > MAX_SOURCE_BYTES:
                result = {'error': 'pdf_limit_exceeded'}
            elif not data.startswith(b'%PDF-'):
                result = {'error': 'pdf_invalid'}
            else:
                result = extract(data)
        except ImportError:
            result = {'error': 'pdf_unavailable'}
        except MemoryError:
            result = {'error': 'pdf_limit_exceeded'}
        except Exception:
            result = {'error': 'pdf_invalid'}
    try:
        output = json.dumps(result, ensure_ascii=False).encode('utf-8')
        if len(output) > MAX_OUTPUT_BYTES:
            output = b'{"error":"pdf_limit_exceeded"}'
        sys.stdout.buffer.write(output)
    except (MemoryError, OSError):
        # Parent treats absent/invalid output as an unconfirmed worker failure.
        pass


if __name__ == '__main__':
    main()
