"""Bounded attachment extraction. Original files remain available on unsupported formats."""
from io import BytesIO
from pathlib import PurePosixPath
import zipfile
from urllib.parse import urlsplit, parse_qs
from .text_encoding import unicode_json

def extract(data,url):
    blocks, status = _extract(data, url)
    result = []
    for block in blocks:
        cleaned = unicode_json(block)
        if cleaned != block:
            cleaned['unicode_repaired'] = True
        result.append(cleaned)
    return result, status


def _extract(data,url):
    # Some official downloads are legacy Office compound files named .docx.
    # Preserve their bytes without feeding them to a ZIP parser or inventing text.
    if data.startswith(b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'):
        return [],'unsupported'
    ext=PurePosixPath(urlsplit(url).path).suffix.lower()
    query={k.lower():v for k,v in parse_qs(urlsplit(url).query).items()}
    if ext not in ('.pdf','.docx','.xlsx','.png','.jpg','.jpeg','.gif','.webp'):
        ext=PurePosixPath(query.get('filename',[''])[0]).suffix.lower() or ext
    if ext in ('.docx','.xlsx'):
        with zipfile.ZipFile(BytesIO(data)) as z:
            if sum(x.file_size for x in z.infolist())>100*1024*1024:raise ValueError('expanded_archive_too_large')
            if len(z.infolist())>10000:raise ValueError('archive_entry_limit')
    if ext=='.pdf':
        from pypdf import PdfReader
        reader=PdfReader(BytesIO(data))
        if len(reader.pages)>500:raise ValueError('page_limit')
        blocks=[{'page':i+1,'text':p.extract_text() or ''} for i,p in enumerate(reader.pages)]
        return blocks,'ready' if any(b['text'].strip() for b in blocks) else 'needs_ocr'
    if ext=='.docx':
        from docx import Document
        d=Document(BytesIO(data));blocks=[{'paragraph':i+1,'text':p.text} for i,p in enumerate(d.paragraphs) if p.text.strip()]
        for ti,t in enumerate(d.tables):
            blocks.extend({'table':ti+1,'row':i+1,'text':' | '.join(c.text for c in r.cells)} for i,r in enumerate(t.rows))
        return blocks,'ready'
    if ext=='.xlsx':
        from openpyxl import load_workbook
        w=load_workbook(BytesIO(data),read_only=True,data_only=True,keep_links=False);blocks=[]
        try:
            for s in w:
                for i,row in enumerate(s.iter_rows(values_only=True)):
                    if len(blocks)>=50000:raise ValueError('row_limit')
                    text=' | '.join(str(x) if x is not None else '' for x in row)
                    if text.strip(' |'):blocks.append({'sheet':s.title,'row':i+1,'text':text})
        finally:w.close()
        return blocks,'ready'
    if ext in ('.png','.jpg','.jpeg','.gif','.webp'):return [],'needs_ocr'
    return [],'unsupported'
