"""Small, restartable collector pipeline. Sources remain disabled until reviewed."""
import hashlib
import time
from datetime import datetime, timezone

from sqlalchemy import select

from .db import transaction
from .domains import DomainBusy
from .enrichment import classify, tokens
from .extraction import extract
from .models import Document, RawObject, Revision, Snapshot, Source, Task
from .network import SafeFetcher
from .parsing import parse_detail
from .adapters import read_list
from .queue import claim, enqueue, finish, defer, keep_lease, assert_ownership, TaskLeaseLost
from .source_health import cooldown_until, record_failure, record_success
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
        existed=db.scalar(select(Task.id).where(Task.key==key))
        task = enqueue(db, "list", key, {"source_id": source_id, "url": url, "page_number": 1, "bucket": bucket})
        if existed is None:
            db.get(Source,source_id).last_scheduled=time.time()
        return int(task is not None and existed is None)


def process_one(factory, settings, worker="worker", fetcher=None):
    task = claim(factory, settings.task_lease_seconds)
    if not task:
        return False
    with keep_lease(factory,task,settings.task_lease_seconds):
        return _process_claimed(factory,settings,task,fetcher)


def _process_claimed(factory, settings, task, fetcher):
    owned_fetcher = fetcher is None
    fetcher = fetcher or SafeFetcher(settings, factory)
    try:
        with factory() as db:
            source = db.get(Source, task["payload"].get("source_id"))
            if not source or not source.enabled:
                finish(factory, task)
                return True
            until = cooldown_until(source)
        if until > time.time():
            defer(factory, task, until)
            return True
        store = make_store(settings)
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
            data, mime, final_url = fetcher.get(url, config["hosts"], page_kind="list", config=config)
            listing = read_list(data, final_url, config)
            items, next_url, listing_audit = listing.items, listing.next_url, listing.audit
            stored = store.put(data, mime)
            with transaction(factory) as db:
                assert_ownership(db,task)
                raw = db.get(RawObject, stored["sha"])
                if not raw:
                    db.add(RawObject(**stored))
                snap = Snapshot(source_id=source_id, url=final_url, raw_sha=stored["sha"], method=getattr(fetcher, "last_mode", "httpx"))
                db.add(snap); db.flush()
                if listing_audit is not None:
                    registered = db.get(Source, source_id)
                    registered.checkpoint = {**(registered.checkpoint or {}), 'last_listing': {
                        **listing_audit, 'unique_eligible_records': len(items), 'snapshot_id': snap.id, 'checked_at': time.time()}}
                for item in items:
                    enqueue(db, "detail", "detail:" + hashlib.sha256((source_id + item["url"] + str(task["payload"].get("bucket", 0))).encode()).hexdigest(),
                            {"source_id": source_id, "item": item, "snapshot_id": snap.id})
                page_number = int(task["payload"].get("page_number", 1))
                bucket = task["payload"].get("bucket", int(time.time() // max(60, int(config.get("interval_seconds", 21600)))))
                max_pages = min(100, max(1, int(config.get("max_pages", 3))))
                if next_url and page_number < max_pages:
                    next_key = "list:" + hashlib.sha256(f"{source_id}:{next_url}:{bucket}".encode()).hexdigest()
                    enqueue(db, "list", next_key, {"source_id": source_id, "url": next_url,
                                                     "page_number": page_number + 1, "bucket": bucket})
            finish(factory, task)
        elif task["kind"] == "detail":
            payload = task["payload"]
            with factory() as db:
                source = db.get(Source, payload["source_id"])
                spec = {"id": source.id, "name": source.name, "region": source.region,
                        "kind": source.kind, "config": dict(source.config)}
            data, mime, final_url = fetcher.get(payload["item"]["url"], spec["config"]["hosts"], page_kind="detail", config=spec["config"])
            item = dict(payload["item"], url=final_url)
            parsed = parse_detail(data, final_url, item, type("RegisteredSource", (), spec)())
            stored = store.put(data, mime)
            with transaction(factory) as db:
                assert_ownership(db,task)
                raw = db.get(RawObject, stored["sha"])
                if not raw: db.add(RawObject(**stored))
                snap = Snapshot(source_id=spec["id"], url=final_url, raw_sha=stored["sha"], method=getattr(fetcher, "last_mode", "httpx")); db.add(snap); db.flush()
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
                        if attachment['status'] != 'pending': continue
                        enqueue(db, "attachment", "attachment:" + hashlib.sha256((str(rev.id) + attachment["url"]).encode()).hexdigest(),
                                {"revision_id": rev.id, "url": attachment["url"], "source_id": spec["id"]})
                doc.updated=datetime.now(timezone.utc).timestamp()
            finish(factory, task)
        elif task["kind"] == "attachment":
            payload = task["payload"]
            with factory() as db:
                source = db.get(Source, payload["source_id"])
                allowed_hosts = list(source.config["hosts"])
            data, mime, final_url = fetcher.get(payload["url"], allowed_hosts, page_kind="attachment", config=source.config)
            metadata = store.put(data, mime)
            blocks, status = extract(data, final_url)
            with transaction(factory) as db:
                assert_ownership(db,task)
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
        record_success(factory, task["payload"].get("source_id"))
    except DomainBusy as exc:
        defer(factory, task, exc.until)
    except TaskLeaseLost:
        pass  # A replacement worker owns the task; do not write or finish its work.
    except Exception as exc:
        until = record_failure(factory, task["payload"].get("source_id"), exc, settings)
        finish(factory, task, f"{type(exc).__name__}:{exc}"[:1000], settings.task_max_attempts, retry_at=until)
    finally:
        if owned_fetcher and hasattr(fetcher, "close"):
            fetcher.close()
    return True
