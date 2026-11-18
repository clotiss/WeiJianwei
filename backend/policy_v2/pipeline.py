"""Small, restartable collector pipeline. Sources remain disabled until reviewed."""
import hashlib
import time

from sqlalchemy import select

from .db import transaction
from .domains import DomainBusy
from .ingestion import persist_detail, persist_snapshot, persist_raw
from .extraction import extract
from .models import Document, Revision, Snapshot, Source, Task
from .network import SafeFetcher, FetchError
from .parsing import parse_detail, ParseError
from .adapters import read_list
from .queue import claim, enqueue, finish, defer, keep_lease, assert_ownership, TaskLeaseLost
from .source_health import cooldown_until, record_failure, record_success
from .storage import make_store
from . import rounds


def discover(factory, source_id, settings=None):
    return rounds.discover(factory, source_id, settings)


def _attachments(db, revision, source_id, run_id):
    # A previous download failure must not require changing the original article.
    for attachment in revision.attachments:
        if attachment['status'] not in ('pending','download_failed'):
            continue
        task = enqueue(db, 'attachment', 'attachment:' + hashlib.sha256(
            (str(revision.id)+attachment['url']).encode()).hexdigest(),
            {'revision_id':revision.id, 'url':attachment['url'], 'source_id':source_id, 'run_id':run_id}, priority=20)
        rounds.link_task(db, run_id, task)


def process_one(factory, settings, worker="worker", fetcher=None):
    task = claim(factory, settings.task_lease_seconds, kinds=('list','detail','attachment'))
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
            if not source:
                finish(factory, task)
                return True
            if not source.enabled:
                defer(factory, task, time.time()+60)
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
                    defer(factory, task, time.time()+60)
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
                persist_raw(db, stored)
                snap = Snapshot(source_id=source_id, url=final_url, raw_sha=stored["sha"], method=getattr(fetcher, "last_mode", "httpx"))
                db.add(snap); db.flush()
                if listing_audit is not None:
                    registered = db.get(Source, source_id)
                    registered.checkpoint = {**(registered.checkpoint or {}), 'last_listing': {
                        **listing_audit, 'unique_eligible_records': len(items), 'snapshot_id': snap.id, 'checked_at': time.time()}}
                for item in items:
                    existing = db.scalar(select(Document).where(Document.url==item['url']))
                    revision = db.get(Revision, existing.current_revision) if existing and existing.current_revision else None
                    recent_page = int(task['payload'].get('page_number',1))<=int(config.get('max_pages',3))
                    due = (not revision or recent_page or existing.updated<time.time()-settings.history_refresh_seconds
                           or revision.title!=item['title'] or (item.get('published') and revision.published!=item['published']))
                    if due:
                        cycle = ('run:'+str(task['payload']['run_id'])) if task['payload'].get('run_id') else str(task['payload'].get('bucket',0))
                        child = enqueue(db, "detail", "detail:" + hashlib.sha256((source_id + item["url"] + cycle).encode()).hexdigest(),
                            {"source_id": source_id, "item": item, "snapshot_id": snap.id,
                             "run_id":task['payload'].get('run_id')})
                        rounds.link_task(db,task['payload'].get('run_id'),child)
                    elif revision:
                        _attachments(db,revision,source_id,task['payload'].get('run_id'))
                page_number = int(task["payload"].get("page_number", 1))
                bucket = task["payload"].get("bucket", int(time.time() // max(60, int(config.get("interval_seconds", 21600)))))
                max_pages = min(100, max(1, int(config.get("max_pages", 3))))
                tracked = rounds.advance_listing(db,db.get(Source,source_id),task,next_url,settings)
                if not tracked and next_url and page_number < max_pages:
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
            stored = store.put(data, mime)
            try:
                parsed = parse_detail(data, final_url, item, type("RegisteredSource", (), spec)())
            except ParseError:
                with transaction(factory) as db:
                    assert_ownership(db, task)
                    persist_snapshot(db, source, stored, final_url, method=getattr(fetcher, 'last_mode', 'httpx'))
                raise
            with transaction(factory) as db:
                assert_ownership(db,task)
                doc, rev, _ = persist_detail(db, source, parsed, stored, final_url,
                    method=getattr(fetcher, "last_mode", "httpx"))
                _attachments(db,rev,spec['id'],task['payload'].get('run_id'))
            finish(factory, task)
        elif task["kind"] == "attachment":
            payload = task["payload"]
            with factory() as db:
                source = db.get(Source, payload["source_id"])
                allowed_hosts = list(source.config["hosts"])
            data, mime, final_url = fetcher.get(payload["url"], allowed_hosts, page_kind="attachment", config=source.config)
            metadata = store.put(data, mime)
            extraction_error = ''
            try:
                blocks, status = extract(data, final_url)
            except Exception as exc:
                # Download/persistence succeeded; retrying identical bytes cannot repair a parser limit.
                # Preserve the original and make incomplete text extraction explicit.
                blocks = []
                status = 'extraction_limited' if isinstance(exc, ValueError) and str(exc) in (
                    'page_limit', 'row_limit', 'expanded_archive_too_large', 'archive_entry_limit') else 'extraction_failed'
                extraction_error = f'{type(exc).__name__}:{exc}'[:500]
            with transaction(factory) as db:
                assert_ownership(db,task)
                persist_raw(db, metadata)
                revision = db.get(Revision, payload["revision_id"])
                attachments = [dict(a) for a in revision.attachments]
                for attachment in attachments:
                    if attachment["url"] == payload["url"]:
                        # Re-downloading unchanged media must not discard a
                        # verified operator OCR/transcription enrichment.
                        if (attachment.get('extraction_method') and attachment.get('extracted')
                                and attachment.get('sha256') == metadata['sha']):
                            continue
                        attachment.update({"status": status, "object_key": metadata["key"],
                                           "sha256": metadata["sha"], "extracted": blocks})
                        attachment.pop('last_error',None)
                        if extraction_error:
                            attachment['extraction_error'] = extraction_error
                        else:
                            attachment.pop('extraction_error', None)
                revision.attachments = attachments
                if revision.summary_status == 'waiting_content': revision.summary_status = 'pending'
            finish(factory, task)
        else:
            raise ValueError("unknown_task_kind")
        record_success(factory, task["payload"].get("source_id"))
    except DomainBusy as exc:
        defer(factory, task, exc.retry_at)
    except TaskLeaseLost:
        pass  # A replacement worker owns the task; do not write or finish its work.
    except Exception as exc:
        # A malformed individual document must not cool down every column on the host.
        # Transport failures still honor origin-wide Retry-After and exponential cooldown.
        until = record_failure(factory, task["payload"].get("source_id"), exc, settings) if isinstance(exc, FetchError) else 0
        finish(factory, task, f"{type(exc).__name__}:{exc}"[:1000], settings.task_max_attempts, retry_at=until)
        rounds.defer_repair(factory,task,settings)
        if task['kind']=='attachment':
            with transaction(factory) as db:
                failed=db.get(Task,task['id'])
                if failed and failed.state=='failed':
                    revision=db.get(Revision,task['payload']['revision_id'])
                    revision.attachments=[{**a,'status':'download_failed','last_error':failed.error}
                        if a['url']==task['payload']['url'] else a for a in revision.attachments]
                    if revision.summary_status == 'waiting_content': revision.summary_status = 'pending'
    finally:
        if owned_fetcher and hasattr(fetcher, "close"):
            fetcher.close()
        rounds.settle(factory,task['payload'].get('source_id'),settings)
    return True
