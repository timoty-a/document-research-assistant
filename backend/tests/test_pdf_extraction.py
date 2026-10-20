import json
import time

import pytest

from app.documents import pdf
from app.documents.pdf_worker import MAX_PAGE_BYTES, MAX_TEXT_BYTES, SEPARATOR
from pdf_samples import pdf_bytes


def test_real_child_extracts_pages_and_preserves_blank_positions():
    start = time.monotonic()
    pages = pdf.extract_pdf(pdf_bytes(('Café evidence.', None, 'Second finding.'), rotate=True))
    assert pages == ('Café evidence.', '', 'Second finding.')
    assert pdf.validate_pages(list(pages)) == 'Café evidence.\n\f\n\n\f\nSecond finding.'
    assert time.monotonic() - start < pdf.WALL_SECONDS


@pytest.mark.parametrize('data,code', [
    (b'not a PDF', 'pdf_invalid'), (b'%PDF-1.7\nbroken', 'pdf_invalid'),
    (pdf_bytes((None,)), 'pdf_no_text'), (pdf_bytes(()), 'pdf_no_text'),
    (pdf_bytes(('   ',)), 'pdf_no_text'),
    (pdf_bytes(password='synthetic-password'), 'pdf_encrypted'),
    (pdf_bytes(password=''), 'pdf_encrypted'),
    (pdf_bytes(tuple('a' for _ in range(101))), 'pdf_limit_exceeded'),
    (pdf_bytes(('a' * (MAX_PAGE_BYTES + 1),)), 'pdf_limit_exceeded'),
], ids=['signature', 'malformed', 'blank', 'zero-pages', 'whitespace', 'encrypted', 'empty-password', 'pages', 'page-text'])
def test_real_worker_rejections(data, code, caplog):
    with pytest.raises(pdf.PDFError) as error:
        pdf.extract_pdf(data)
    assert error.value.code == code
    assert not caplog.text


def test_exact_page_and_aggregate_limits():
    assert len(pdf.validate_pages(['a' * MAX_PAGE_BYTES]).encode()) == MAX_PAGE_BYTES
    assert len(pdf.extract_pdf(pdf_bytes(tuple('a' for _ in range(100))))) == 100
    pages = ['a' * MAX_PAGE_BYTES] * 7
    pages.append('a' * (MAX_TEXT_BYTES - sum(map(len, pages)) - 7 * len(SEPARATOR)))
    assert len(pdf.validate_pages(pages).encode()) == MAX_TEXT_BYTES
    with pytest.raises(pdf.PDFError, match='pdf_limit_exceeded'):
        pdf.validate_pages(pages[:-1] + [pages[-1] + 'a'])


@pytest.mark.parametrize('pages', [[], [1], ['a\x00'], ['\ud800'], ['  ', '']])
def test_parent_validates_untrusted_output(pages):
    with pytest.raises(pdf.PDFError):
        pdf.validate_pages(pages)


def test_busy_slot_and_release_after_failure(monkeypatch):
    assert pdf._SLOT.acquire(False)
    try:
        with pytest.raises(pdf.PDFError, match='pdf_busy'):
            pdf.extract_pdf(b'%PDF-')
    finally:
        pdf._SLOT.release()
    with pytest.raises(pdf.PDFError):
        pdf.extract_pdf(b'%PDF-')
    assert pdf._SLOT.acquire(False)
    pdf._SLOT.release()


def test_watchdog_kills_reaps_child_and_releases_slot(tmp_path, monkeypatch):
    script = tmp_path / 'slow.py'
    script.write_text('import time\ntime.sleep(60)\n')
    monkeypatch.setattr(pdf, 'WORKER', script)
    monkeypatch.setattr(pdf, 'WALL_SECONDS', 0.05)
    original = pdf.subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        return child
    monkeypatch.setattr(pdf.subprocess, 'Popen', spawn)
    with pytest.raises(pdf.PDFError, match='pdf_limit_exceeded'):
        pdf.extract_pdf(b'%PDF-')
    assert children[0].returncode is not None
    assert pdf._SLOT.acquire(False)
    pdf._SLOT.release()


def test_real_address_space_limit_and_private_environment(tmp_path, monkeypatch):
    # Actual OS limit, controlled allocation; not a claim about a hostile corpus.
    script = tmp_path / 'memory.py'
    script.write_text(f'''import runpy, os, json
worker = runpy.run_path({str(pdf.WORKER)!r})
worker['apply_limits']()
assert not any('PASSWORD' in key or 'TOKEN' in key for key in os.environ)
try:
    x = bytearray(worker['MEMORY_BYTES'])
except MemoryError:
    print(json.dumps({{'error': 'pdf_limit_exceeded'}}))
''')
    monkeypatch.setattr(pdf, 'WORKER', script)
    with pytest.raises(pdf.PDFError, match='pdf_limit_exceeded'):
        pdf.extract_pdf(b'%PDF-')


@pytest.mark.parametrize('output', [b'invalid', b'[]', b'{"pages":[1]}', b'{"error":"private exception"}'])
def test_invalid_worker_protocol_is_sanitized(output, tmp_path, monkeypatch):
    script = tmp_path / 'output.py'
    script.write_text(f'import sys\nsys.stdout.buffer.write({output!r})\n')
    monkeypatch.setattr(pdf, 'WORKER', script)
    with pytest.raises(pdf.PDFError) as error:
        pdf.extract_pdf(b'%PDF-')
    assert 'private' not in error.value.detail


def test_image_only_and_existing_text_over_image():
    with pytest.raises(pdf.PDFError, match='pdf_no_text'):
        pdf.extract_pdf(pdf_bytes((None,), image=True))
    assert pdf.extract_pdf(pdf_bytes(('Existing OCR-like layer.',), image=True)) == ('Existing OCR-like layer.',)


def test_real_cpu_limit_terminates_child(tmp_path, monkeypatch):
    script = tmp_path / 'cpu.py'
    script.write_text('import resource\nresource.setrlimit(resource.RLIMIT_CPU, (1, 2))\nwhile True: pass\n')
    monkeypatch.setattr(pdf, 'WORKER', script)
    with pytest.raises(pdf.PDFError, match='pdf_limit_exceeded'):
        pdf.extract_pdf(b'%PDF-')


def test_real_worker_output_file_is_capped(tmp_path, monkeypatch):
    script = tmp_path / 'output_limit.py'
    script.write_text(f'''import runpy, os
worker = runpy.run_path({str(pdf.WORKER)!r})
worker['apply_limits']()
os.write(1, b'x' * (worker['MAX_OUTPUT_BYTES'] + 1024))
os.write(1, b'x')
''')
    monkeypatch.setattr(pdf, 'WORKER', script)
    with pytest.raises(pdf.PDFError):
        pdf.extract_pdf(b'%PDF-')


def test_parent_reaps_child_on_interruption_and_releases_slot(tmp_path, monkeypatch):
    script = tmp_path / 'interrupted.py'
    script.write_text('import time\ntime.sleep(60)\n')
    monkeypatch.setattr(pdf, 'WORKER', script)
    original = pdf.subprocess.Popen
    children = []
    def spawn(*args, **kwargs):
        child = original(*args, **kwargs)
        children.append(child)
        wait = child.wait
        calls = [0]
        def interrupt_once(*args, **kwargs):
            calls[0] += 1
            if calls[0] == 1:
                raise KeyboardInterrupt()
            return wait(*args, **kwargs)
        child.wait = interrupt_once
        return child
    monkeypatch.setattr(pdf.subprocess, 'Popen', spawn)
    with pytest.raises(KeyboardInterrupt):
        pdf.extract_pdf(b'%PDF-')
    assert children[0].poll() is not None
    assert pdf._SLOT.acquire(False)
    pdf._SLOT.release()


def test_worker_enforces_page_and_aggregate_output_bounds(monkeypatch):
    from app.documents import pdf_worker
    monkeypatch.setattr(pdf_worker, 'MAX_PAGE_BYTES', 8)
    assert pdf_worker.extract(pdf_bytes(('a' * 8,))) == {'pages': ['a' * 8]}
    assert pdf_worker.extract(pdf_bytes(('a' * 9,))) == {'error': 'pdf_limit_exceeded'}
    monkeypatch.setattr(pdf_worker, 'MAX_TEXT_BYTES', 10)
    assert pdf_worker.extract(pdf_bytes(('a' * 4, 'a' * 4))) == {'error': 'pdf_limit_exceeded'}


def test_positioned_columns_preserve_extractor_order_without_claiming_layout():
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    from pypdf.generic import DecodedStreamObject, NameObject
    reader = PdfReader(BytesIO(pdf_bytes()))
    writer = PdfWriter()
    page = writer.add_page(reader.pages[0])
    stream = DecodedStreamObject()
    stream.set_data(b'BT /F1 12 Tf 320 720 Td (Right column.) Tj ET BT /F1 12 Tf 72 720 Td (Left column.) Tj ET')
    page[NameObject('/Contents')] = writer._add_object(stream)
    output = BytesIO(); writer.write(output)
    pages = pdf.extract_pdf(output.getvalue())
    assert pages == ('Right column.Left column.',)


def test_encrypted_reader_never_attempts_password_verification(monkeypatch):
    from pypdf._encryption import Encryption
    from app.documents.pdf_worker import extract
    source = pdf_bytes(password='')
    def forbidden(*args, **kwargs):
        pytest.fail('Encrypted inputs must not attempt password verification')
    monkeypatch.setattr(Encryption, 'verify', forbidden)
    assert extract(source) == {'error': 'pdf_encrypted'}
