"""Import hash-verified original pages, never the abbreviated validation report as body text."""
import gzip
import hashlib
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from .db import transaction
from .extraction import extract
from .ingestion import persist_detail
from .models import Audit, RawObject, Source
from .parsing import parse_detail
from .pipeline import _attachments
from .sources import source_definitions
from .storage import make_store


def verified_bytes(path, digest):
    raw = Path(path).read_bytes()
    if str(path).endswith('.gz'):
        raw = gzip.decompress(raw)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise ValueError('evidence_hash_mismatch:' + str(path))
    return raw


def import_verified(factory, settings, report_path, *, workspace, attachment_report=None, attachment_root=None):
    workspace = Path(workspace).resolve()
    definitions = {s['id']: s for s in source_definitions() if s.get('config') and s['status'] == 'sample_pass'}
    reports = json.loads(Path(report_path).read_text())
    if {r['id'] for r in reports} != set(definitions) or len(reports) != len(definitions):
        raise ValueError('evidence_must_cover_all_verified_sources')
    prepared = []
    # Validate every source and raw page before any document is written or enabled.
    for report in reports:
        spec = definitions[report['id']]
        digest = hashlib.sha256(json.dumps(spec['config'], sort_keys=True).encode()).hexdigest()
        if report['status'] != 'sample_pass' or report['config_sha256'] != digest:
            raise ValueError('evidence_configuration_mismatch:' + spec['id'])
        fetched = datetime.fromisoformat(report['checked_at']).timestamp()
        good = [d for d in report['details'] if d['status'] == 'ok']
        if not good or len(good) != report['sample_ok']:
            raise ValueError('evidence_sample_count_mismatch:' + spec['id'])
        for detail in good:
            path = (workspace / detail['path']).resolve()
            if not path.is_relative_to(workspace):
                raise ValueError('evidence_path_outside_workspace')
            raw = verified_bytes(path, detail['sha256'])
            parsed = parse_detail(raw, detail['url'], {'title': detail['list_title'],
                'published': detail.get('published')}, SimpleNamespace(**spec))
            if not parsed['published'] or parsed['title'] != detail['title'] or len(parsed['body']) != detail['body_chars']:
                raise ValueError('evidence_parse_mismatch:' + detail['url'])
            prepared.append((spec['id'], detail['url'], parsed, raw, fetched))
    cached_attachments = {}
    if attachment_report and attachment_root:
        root = Path(attachment_root).resolve()
        for item in json.loads(Path(attachment_report).read_text()):
            if item['status'] != 'stored':
                continue
            path = (root / item['object_key']).resolve()
            if not path.is_relative_to(root):
                raise ValueError('attachment_path_outside_store')
            data = verified_bytes(path, item['sha256'])
            blocks, status = extract(data, item['url'])
            cached_attachments[(item['source'], item['url'])] = (data, item['mime'], blocks, status)
    store = make_store(settings)
    counts = {}; changed = 0
    for sid, url, parsed, raw, fetched in prepared:
        stored = store.put(raw, 'text/html')
        with transaction(factory) as db:
            source = db.get(Source, sid)
            if source is None:
                raise ValueError('source_not_seeded:' + sid)
            _, revision, new = persist_detail(db, source, parsed, stored, url, method='verified-cache', fetched=fetched)
            changed += int(new)
            attachments = [dict(a) for a in revision.attachments]
            for attachment in attachments:
                cached = cached_attachments.get((sid, attachment['url']))
                if cached and attachment['status'] in ('pending', 'download_failed'):
                    data, mime, blocks, status = cached
                    metadata = store.put(data, mime)
                    if not db.get(RawObject, metadata['sha']):
                        db.add(RawObject(**metadata)); db.flush()
                    attachment.update(status=status, object_key=metadata['key'], sha256=metadata['sha'], extracted=blocks)
            revision.attachments = attachments
            _attachments(db, revision, sid, None)
        counts[sid] = counts.get(sid, 0) + 1
    manifest_sha = hashlib.sha256(Path(report_path).read_bytes()).hexdigest()
    with transaction(factory) as db:
        for source in db.scalars(select(Source)):
            if source.id in counts:
                source.checkpoint = {**(source.checkpoint or {}), 'verified_import': {
                    'samples': counts[source.id], 'manifest_sha256': manifest_sha}}
        db.add(Audit(actor='national-service', action='evidence.import', target=manifest_sha,
            reason='Import reviewed original pages with SHA-256 and parser verification',
            after={'samples': len(prepared), 'new_revisions': changed, 'sources': len(counts)}))
    return {'samples': len(prepared), 'new_revisions': changed, 'sources': len(counts), 'by_source': counts}
