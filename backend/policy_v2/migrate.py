"""One-way, repeatable import of legacy SQLite documents into the V2 schema."""
import hashlib
import json
import sqlite3

from sqlalchemy import select

from .models import Document, Revision, Source
from .parsing import canonical


TYPE_MAP = {"规范性文件": "policy", "政策解读": "interpretation"}


def migrate_documents(legacy_path, factory):
    """Import documents preserving numeric IDs; historical raw snapshots stay absent."""
    conn = sqlite3.connect(legacy_path)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute("SELECT * FROM documents ORDER BY id").fetchall()
    finally:
        conn.close()
    imported = skipped = 0
    with factory.begin() as db:
        sources = {s.id: s for s in db.scalars(select(Source)).all()}
        for row in rows:
            kind = TYPE_MAP.get(row["doc_type"] or "")
            url = canonical(row["original_url"] or "")
            if not kind or not url.startswith("https://"):
                skipped += 1
                continue
            source = sources.get("nhc-" + kind)
            if not source:
                skipped += 1
                continue
            existing = db.scalar(select(Document).where(Document.legacy_id == row["id"]))
            if existing:
                continue
            doc = Document(legacy_id=row["id"], source_id=source.id, url=url, region="CN", status="ready")
            db.add(doc); db.flush()
            attachments = _json_list(row["attachments"])
            summary = _json_list(row["summary"])
            title, body = row["title"] or "", row["content"] or ""
            fingerprint = hashlib.sha256((title + "\n" + body + "\n" + str(row["publish_date"] or "")).encode()).hexdigest()
            revision = Revision(document_id=doc.id, number=1, fingerprint=fingerprint,
                title=title, body=body, authority=row["issuing_authority"] or "国家卫生健康委",
                published=(row["publish_date"] or "")[:10] or None,
                doc_number=row["doc_number"] or "", kind=kind, topic=row["category"] or "",
                classification_status="legacy_unverified" if row["category"] else "review",
                summary=summary, attachments=attachments,
                search_text=" ".join([title, row["doc_number"] or "", body]))
            db.add(revision); db.flush(); doc.current_revision=revision.id
            imported += 1
    return {"imported": imported, "skipped": skipped, "total": len(rows)}


def _json_list(value):
    if not value: return []
    try:
        result = json.loads(value)
        return result if isinstance(result, list) else []
    except (ValueError, TypeError):
        return []
