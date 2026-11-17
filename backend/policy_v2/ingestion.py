"""Persist parsed official content identically for live collection and evidence import."""
import hashlib
import time

from sqlalchemy import select
from .enrichment import classify, tokens
from .models import Document, RawObject, Revision, Snapshot


def fingerprint(parsed):
    value = '\n'.join([parsed['title'], parsed['body'], parsed['published'] or '',
                       *(a['url'] for a in parsed['attachments'])])
    return hashlib.sha256(value.encode()).hexdigest()


def persist_snapshot(db, source, stored, url, *, method, fetched=None):
    fetched = time.time() if fetched is None else fetched
    if not db.get(RawObject, stored['sha']):
        db.add(RawObject(**stored))
    snapshot = db.scalar(select(Snapshot).where(Snapshot.source_id == source.id,
        Snapshot.url == url, Snapshot.raw_sha == stored['sha'], Snapshot.method == method))
    if snapshot is None:
        snapshot = Snapshot(source_id=source.id, url=url, raw_sha=stored['sha'], method=method, fetched=fetched)
        db.add(snapshot); db.flush()
    return snapshot


def persist_detail(db, source, parsed, stored, url, *, method, fetched=None):
    fetched = time.time() if fetched is None else fetched
    snapshot = persist_snapshot(db, source, stored, url, method=method, fetched=fetched)
    doc = db.scalar(select(Document).where(Document.url == url))
    if doc is None:
        doc = Document(source_id=source.id, url=url, region=source.region)
        db.add(doc); db.flush()
    latest = db.scalar(select(Revision).where(Revision.document_id == doc.id).order_by(Revision.number.desc()).limit(1))
    digest = fingerprint(parsed)
    # Imported cached pages must never replace content refreshed since the evidence was captured.
    if latest and method == 'verified-cache' and doc.updated > fetched:
        return doc, latest, False
    changed = latest is None or latest.fingerprint != digest
    if changed:
        topic, evidence = classify(parsed['title'], parsed['body'])
        text = ' '.join([parsed['title'], parsed['body']])
        latest = Revision(document_id=doc.id, number=latest.number + 1 if latest else 1,
            fingerprint=digest, snapshot_id=snapshot.id, title=parsed['title'], body=parsed['body'],
            authority=parsed['authority'], published=parsed['published'], doc_number=parsed['doc_number'],
            kind=parsed['kind'], topic=topic, classification_status='auto' if topic else 'review',
            classification_evidence=evidence, attachments=parsed['attachments'], search_text=text,
            search_tokens=tokens(text))
        db.add(latest); db.flush()
        doc.current_revision = latest.id
        doc.status = 'excluded' if parsed['kind'] == 'excluded' else 'ready'
    doc.updated = max(doc.updated if not changed else 0, fetched)
    return doc, latest, changed
