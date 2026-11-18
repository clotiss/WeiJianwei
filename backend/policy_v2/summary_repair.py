"""Import a bounded operator-generated repair bundle with source and quote guards.

Only failed current revisions can change. Original HTML/body is immutable. Media
text must be tied to original bytes verified locally or fetched from an allowed
source host. No model calls or credentials are stored in the bundle.
"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .models import Audit, Document, RawObject, Revision, Source, Snapshot, SummaryRecord, Task, now
from .network import SafeFetcher
from .queue import enqueue
from .storage import make_store
from .summaries import exclusion_reason, summary_input, validate_points


class RepairError(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def check_revision(document, revision, item):
    return (document and revision and document.status == 'ready'
        and document.url == item['url'] and revision.number == item['revision']
        and revision.title == item['title'] and revision.published == item['published']
        and digest(revision.body) == item['body_sha256']
        and [a['url'] for a in revision.attachments] in (item['attachment_urls'],
            item['attachment_urls'] + [p['url'] for p in item.get('media', []) if p.get('append')])
        and not exclusion_reason(revision.published))


def import_bundle(factory, settings, bundle, *, asset_root=None, fetcher=None):
    if bundle.get('format') != 1 or not isinstance(bundle.get('items'), list):
        raise RepairError('invalid_repair_bundle')
    ids = [item['id'] for item in bundle['items']]
    if len(ids) != len(set(ids)) or len(ids) > 1000: raise RepairError('invalid_repair_cohort')
    bundle_sha = digest(json.dumps(bundle, sort_keys=True, ensure_ascii=False))
    store = make_store(settings)
    report = {'ready': [], 'already_ready': [], 'skipped': [], 'failed': []}
    owned_fetcher = fetcher is None
    fetcher = fetcher or SafeFetcher(settings)
    try:
        for item in bundle['items']:
            try:
                with factory() as db:
                    document = db.get(Document, item['id'])
                    revision = db.get(Revision, document.current_revision) if document else None
                    if not check_revision(document, revision, item):
                        report['skipped'].append({'id': item['id'], 'reason': 'source_changed'}); continue
                    if revision.summary_status == 'ready':
                        report['already_ready'].append(item['id']); continue
                    if revision.summary_status != 'failed':
                        report['skipped'].append({'id': item['id'], 'reason': 'not_failed'}); continue
                    source = db.get(Source, document.source_id)
                    config = copy.deepcopy(source.config)
                    observed_attachments = copy.deepcopy(revision.attachments)
                    attachments = copy.deepcopy(observed_attachments)
                    snapshot = db.get(Snapshot, revision.snapshot_id) if revision.snapshot_id else None
                    original = db.get(RawObject, snapshot.raw_sha) if snapshot else None
                    original_key = original.key if original else None
                    original_sha = original.sha if original else None
                # Stage and verify originals before acquiring a database write lock.
                stored = []
                for patch in item.get('media', []):
                    index = patch['index']
                    if patch.get('append'):
                        if index != len(attachments) or patch.get('kind') != 'audio' or not original_key:
                            raise RepairError('invalid_new_media')
                        html = store.read(original_key)
                        if hashlib.sha256(html).hexdigest() != original_sha:
                            raise RepairError('original_snapshot_hash_mismatch')
                        soup = BeautifulSoup(html, 'lxml')
                        links = {urljoin(document.url, node.get('href') or node.get('src') or '')
                                 for node in soup.select('a[href], audio[src], source[src]')}
                        if patch['url'] not in links or not urlsplit(patch['url']).path.lower().endswith('.mp3'):
                            raise RepairError('audio_not_in_saved_original')
                        attachments.append({'url': patch['url'], 'name': '官方音频（文字转写）', 'audio': True})
                    attachment = attachments[index]
                    if not (attachment.get('image') or attachment.get('audio')) or attachment['url'] != patch['url']:
                        raise RepairError('attachment_identity_changed')
                    if attachment.get('sha256') and attachment['sha256'] != patch['sha256']:
                        raise RepairError('attachment_bytes_changed')
                    sha = patch['sha256']
                    if len(sha) != 64 or any(c not in '0123456789abcdef' for c in sha):
                        raise RepairError('invalid_attachment_hash')
                    key = f'raw/{sha[:2]}/{sha}'
                    try:
                        data = store.read(key); mime = 'application/octet-stream'
                    except FileNotFoundError:
                        local = Path(asset_root) / f"{item['id']}-{index}" if asset_root else None
                        if local and local.is_file(): data, mime = local.read_bytes(), 'application/octet-stream'
                        else: data, mime, _ = fetcher.get(patch['url'], config['hosts'], page_kind='attachment', config=config)
                    if hashlib.sha256(data).hexdigest() != sha: raise RepairError('attachment_hash_mismatch')
                    metadata = store.put(data, mime)
                    stored.append(metadata)
                    blocks = patch['extracted']
                    if (not isinstance(blocks, list) or not blocks or len(blocks) > 100
                        or any(not isinstance(b.get('text'), str) or not 1 <= len(b['text']) <= 100000 for b in blocks)):
                        raise RepairError('invalid_media_text')
                    attachment.update(status='ready', sha256=sha, object_key=key,
                                      extracted=blocks, extraction_method=patch['method'])
                    if patch.get('scope') == 'excerpt': attachment['extraction_scope'] = 'excerpt'
                    attachment.pop('last_error', None)
                result = item['result']
                with factory.begin() as db:
                    document = db.get(Document, item['id'])
                    revision = db.get(Revision, document.current_revision) if document else None
                    if not check_revision(document, revision, item) or revision.summary_status != 'failed':
                        raise RepairError('revision_changed_during_repair')
                    record = db.get(SummaryRecord, revision.id)
                    old_task = db.get(Task, record.task_id) if record else None
                    if old_task and old_task.state == 'running': raise RepairError('summary_in_flight')
                    # Preserve any concurrently completed attachment extraction.
                    if revision.attachments != observed_attachments:
                        raise RepairError('attachment_changed_during_repair')
                    content, state = summary_input(SimpleNamespace(title=revision.title, body=revision.body, attachments=attachments))
                    if not content or content['sha'] != result['input_sha']: raise RepairError('summary_input_changed')
                    if result['state'] != 'ready' or result['prompt_version'] not in ('evidence-v3', 'evidence-v4'):
                        raise RepairError('invalid_repair_result')
                    points = validate_points({'points': result['points']}, content['segments'])
                    if points != result['points']: raise RepairError('citation_offsets_changed')
                    for metadata in stored:
                        if not db.get(RawObject, metadata['sha']): db.add(RawObject(**metadata))
                    task = enqueue(db, 'summary', f'summary-repair:{bundle_sha}:{revision.id}',
                        {'revision_id': revision.id, 'input_sha': content['sha'], 'model': result['model'],
                         'prompt_version': result['prompt_version'], 'repair_bundle': bundle_sha})
                    task.state, task.attempts, task.finished = 'succeeded', 1, now()
                    values = dict(task_id=task.id, input_sha=content['sha'], model=result['model'],
                                  prompt_version=result['prompt_version'], scope=content['scope'], input_chars=content['chars'],
                                  generated=result['generated_at'], usage=result['usage'])
                    if record is None: db.add(SummaryRecord(revision_id=revision.id, **values))
                    else:
                        for key, value in values.items(): setattr(record, key, value)
                    revision.attachments = attachments
                    revision.summary, revision.summary_status = points, 'ready'
                    # An old queued download must not replace OCR with needs_ocr.
                    media_urls = {patch['url'] for patch in item.get('media', [])}
                    if media_urls:
                        for queued in db.scalars(select(Task).where(Task.kind == 'attachment',
                                Task.state.in_(('queued', 'failed')), Task.payload['revision_id'].as_integer() == revision.id)):
                            if queued.payload.get('url') in media_urls:
                                queued.state, queued.finished, queued.error = 'cancelled', now(), 'replaced_by_verified_media_text'
                    db.add(Audit(actor='summary-repair', action='summary.repaired', target=str(revision.id),
                        reason='User requested repair of the captured 434 failed summaries',
                        after={'bundle_sha256': bundle_sha, 'input_sha': content['sha'], 'model': result['model'],
                               'prompt_version': result['prompt_version'], 'scope': content['scope'],
                               'original_media': [m['sha'] for m in stored]}))
                report['ready'].append(item['id'])
            except Exception as exc:
                # Do not expose provider/configuration content in errors.
                report['failed'].append({'id': item['id'], 'reason': str(exc) if isinstance(exc, RepairError) else type(exc).__name__})
    finally:
        if owned_fetcher: fetcher.close()
    return report


def main():
    import argparse
    from .national_service import open_service
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--asset-root', type=Path)
    args = parser.parse_args()
    bundle = json.loads(args.bundle.read_text())
    settings, engine, factory = open_service(args.root)
    try:
        report = import_bundle(factory, settings, bundle, asset_root=args.asset_root)
        print(json.dumps({'counts': {key: len(value) for key, value in report.items()}, **report}, ensure_ascii=False), flush=True)
        if report['failed'] or report['skipped']: raise SystemExit(2)
    finally:
        engine.dispose()


if __name__ == '__main__': main()
