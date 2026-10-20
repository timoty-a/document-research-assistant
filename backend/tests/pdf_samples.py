"""Generate authored synthetic PDFs in memory; no uploaded/private fixtures."""
from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject, NumberObject


def pdf_bytes(pages=('Synthetic research source.',), *, password=None, rotate=False, padding=0, image=False):
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'),
                                 NameObject('/BaseFont'): NameObject('/Helvetica'), NameObject('/Encoding'): NameObject('/WinAnsiEncoding')})
        page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
        image_ops = b''
        if image:
            bitmap = DecodedStreamObject()
            bitmap.set_data(b'\xff\xff\xff')
            bitmap.update({NameObject('/Type'): NameObject('/XObject'), NameObject('/Subtype'): NameObject('/Image'),
                           NameObject('/Width'): NumberObject(1), NameObject('/Height'): NumberObject(1),
                           NameObject('/ColorSpace'): NameObject('/DeviceRGB'), NameObject('/BitsPerComponent'): NumberObject(8)})
            page['/Resources'][NameObject('/XObject')] = DictionaryObject({NameObject('/Im1'): writer._add_object(bitmap)})
            image_ops = b'q 100 0 0 100 72 500 cm /Im1 Do Q\n'
        if text is not None or image:
            stream = DecodedStreamObject()
            stream.set_data(image_ops + (b'BT /F1 12 Tf 72 720 Td <' + text.encode('cp1252').hex().encode() + b'> Tj ET' if text is not None else b''))
            page[NameObject('/Contents')] = writer._add_object(stream)
        if rotate:
            page.rotate(90)
    if padding:
        writer.add_metadata({'/SyntheticPadding': 'x' * padding})
    if password is not None:
        writer.encrypt(password)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()
