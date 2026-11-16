"""Small, restartable collector pipeline. Sources remain disabled until reviewed."""
import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .db import transaction
from .enrichment import classify, tokens
from .extraction import extract
from .models import Document, RawObject, Revision, Snapshot, Source, Task
from .network import SafeFetcher
from .parsing import parse_detail, parse_list
from .queue import claim, enqueue, finish
from .storage import make_store


def _fingerprint(title, body, published, attachments):
    value = "\n".join([title, body, published or "", *(a["url"] for a in attachments)])
    return hashlib.sha256(value.encode()).hexdigest()


def discover(factory, source_id):
    """Schedule bounded list-page work for one registered source."""
    with factory() as db:
        source = db.get(Source, source_id)
        if not source or not source.enabled:
            return 0
        spec = {"id": source.id, "url": source.url, "interval": source.interval_seconds}
    url = spec["url"]
    bucket = int(time.time() // max(60, spec["interval"]))
    key = "list:" + hashlib.sha256(f"{source_id}:{url}:{bucket}".encode()).hexdigest()
    with transaction(factory) as db:
        task = enqueue(db, "list", key, {"source_id": source_id, "url": url, "page_number": 1, "bucket": bucket})
        return int(task is not None)


def process_one(factory, settings, worker="worker"):
    task = claim(factory, settings.task_lease_seconds)
    if not task:
        return False
    try:
        store = make_store(settings)
        fetcher = SafeFetcher(settings)
        if task["kind"] == "list":
            source_id, url = task["payload"]["source_id"], task["payload"]["url"]
            with factory() as db:
                source = db.get(Source, source_id)
                if not source or not source.enabled:
                    finish(factory, task)
                    return True
                config = dict(source.config)
                spec = {"id": source.id, "kind": source.kind, "name": source.name,
                        "region": source.region, "config": config}
            data, mime, final_url = fetcher.get(url, config["hosts"])
            items, next_url = parse_list(data, final_url, config)
            stored = store.put(data, mime)
            with transaction(factory) as db:
                raw = db.get(RawObject, stored["sha"])
                if not raw:
                    db.add(RawObject(**stored))
                snap = Snapshot(source_id=source_id, url=final_url, raw_sha=stored["sha"], method="http")
                db.add(snap); db.flush()
                for item in items:
                    enqueue(db, "detail", "detail:" + hashlib.sha256((source_id + item["url"]).encode()).hexdigest(),
                            {"source_id": source_id, "item": item, "snapshot_id": snap.id})
                page_number = int(task["payload"].get("page_number", 1))
                bucket = task["payload"].get("bucket", int(time.time() // max(60, int(config.get("interval_seconds", 21600)))))
                max_pages = min(3, max(1, int(config.get("max_pages", 1))))
                if next_url and page_number < max_pages:
                    next_key = "list:" + hashlib.sha256(f"{source_id}:{next_url}:{bucket}".encode()).hexdigest()
                    enqueue(db, "list", next_key, {"source_id": source_id, "url": next_url,
                                                     "page_number": page_number + 1, "bucket": bucket})
                source.last_success = datetime.now(timezone.utc).timestamp()
                source.last_error = ""
            finish(factory, task)
        elif task["kind"] == "detail":
            payload = task["payload"]
            with factory() as db:
                source = db.get(Source, payload["source_id"])
                spec = {"id": source.id, "name": source.name, "region": source.region,
                        "kind": source.kind, "config": dict(source.config)}
            data, mime, final_url = fetcher.get(payload["item"]["url"], spec["config"]["hosts"])
            item = dict(payload["item"], url=final_url)
            parsed = parse_detail(data, final_url, item, type("RegisteredSource", (), spec)())
            stored = store.put(data, mime)
            with transaction(factory) as db:
                raw = db.get(RawObject, stored["sha"])
                if not raw: db.add(RawObject(**stored))
                snap = Snapshot(source_id=spec["id"], url=final_url, raw_sha=stored["sha"]); db.add(snap); db.flush()
                doc = db.scalar(select(Document).where(Document.url == final_url))
                if not doc:
                    doc = Document(source_id=spec["id"], url=final_url, region=spec["region"]); db.add(doc); db.flush()
                fingerprint = _fingerprint(parsed["title"], parsed["body"], parsed["published"], parsed["attachments"])
                latest = db.scalar(select(Revision).where(Revision.document_id == doc.id).order_by(Revision.number.desc()).limit(1))
                if not latest or latest.fingerprint != fingerprint:
                    topic, evidence = classify(parsed["title"], parsed["body"])
                    rev = Revision(document_id=doc.id, number=(latest.number + 1 if latest else 1), fingerprint=fingerprint,
                        snapshot_id=snap.id, title=parsed["title"], body=parsed["body"], authority=parsed["authority"],
                        published=parsed["published"], doc_number=parsed["doc_number"], kind=parsed["kind"],
                        topic=topic, classification_status="auto" if topic else "review", classification_evidence=evidence,
                        attachments=parsed["attachments"], search_text=" ".join([parsed["title"], parsed["body"]]),
                        search_tokens=tokens(" ".join([parsed["title"], parsed["body"]])))
                    db.add(rev); db.flush(); doc.current_revision=rev.id; doc.status="ready" if parsed["kind"]!='excluded' else "excluded"
                    for attachment in parsed["attachments"]:
                        enqueue(db, "attachment", "attachment:" + hashlib.sha256((str(rev.id) + attachment["url"]).encode()).hexdigest(),
                                {"revision_id": rev.id, "url": attachment["url"], "source_id": spec["id"]})
                doc.updated=datetime.now(timezone.utc).timestamp()
            finish(factory, task)
        elif task["kind"] == "attachment":
            payload = task["payload"]
            with factory() as db:
                source = db.get(Source, payload["source_id"])
                allowed_hosts = list(source.config["hosts"])
            data, mime, final_url = fetcher.get(payload["url"], allowed_hosts)
            metadata = store.put(data, mime)
            blocks, status = extract(data, final_url)
            with transaction(factory) as db:
                raw = db.get(RawObject, metadata["sha"])
                if not raw: db.add(RawObject(**metadata))
                revision = db.get(Revision, payload["revision_id"])
                attachments = [dict(a) for a in revision.attachments]
                for attachment in attachments:
                    if attachment["url"] == payload["url"]:
                        attachment.update({"status": status, "object_key": metadata["key"],
                                           "sha256": metadata["sha"], "extracted": blocks})
                revision.attachments = attachments
            finish(factory, task)
        else:
            raise ValueError("unknown_task_kind")
    except Exception as exc:
        finish(factory, task, f"{type(exc).__name__}:{exc}"[:1000], settings.task_max_attempts)
        with transaction(factory) as db:
            source_id = task["payload"].get("source_id")
            source = db.get(Source, source_id) if source_id else None
            if source: source.last_error = f"{type(exc).__name__}:{exc}"[:500]
    return True
