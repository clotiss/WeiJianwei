import hashlib
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from policy_v2.db import Base, database
from policy_v2.models import CollectionRun, Document, Revision, Snapshot, Source, Task
from policy_v2.settings import Settings
from policy_v2.storage import LocalStore
from policy_v2.ingestion import persist_detail
from policy_v2 import verified_import
from policy_v2.national_service import open_service, enable_verified


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    settings = Settings(database_url='sqlite:///' + str(tmp_path / 'test.db'), object_root=tmp_path / 'objects')
    engine, factory = database(settings.database_url)
    Base.metadata.create_all(engine)
    spec = {'id': 'sample', 'name': 'Official', 'region': 'CN', 'kind': 'policy', 'status': 'sample_pass',
        'url': 'https://official.gov.cn/list.html',
        'config': {'hosts': ['official.gov.cn'], 'body_selectors': ['#body']}}
    with factory.begin() as db:
        db.add(Source(**{k: spec[k] for k in ('id', 'name', 'region', 'kind', 'url', 'config')}))
    monkeypatch.setattr(verified_import, 'source_definitions', lambda: [spec])
    raw = '<meta name="ArticleTitle" content="健康政策通知"><div id="body">' + '健康政策正文。' * 20 + '</div>'
    (tmp_path / 'original.html').write_text(raw)
    parsed = verified_import.parse_detail(raw.encode(), 'https://official.gov.cn/a.html',
        {'title': '健康政策通知', 'published': '2026-10-01'}, SimpleNamespace(**spec))
    report = [{'id': 'sample', 'status': 'sample_pass', 'checked_at': '2026-11-01T00:00:00+00:00',
        'config_sha256': hashlib.sha256(json.dumps(spec['config'], sort_keys=True).encode()).hexdigest(),
        'sample_ok': 1, 'details': [{'url': 'https://official.gov.cn/a.html', 'path': 'original.html',
            'sha256': hashlib.sha256(raw.encode()).hexdigest(), 'status': 'ok', 'title': parsed['title'],
            'list_title': parsed['title'], 'published': parsed['published'], 'body_chars': len(parsed['body'])}]}]
    (tmp_path / 'report.json').write_text(json.dumps(report))
    yield factory, settings, tmp_path, parsed
    engine.dispose()


def test_verified_import_persists_original_body_and_is_idempotent(dataset):
    factory, settings, root, parsed = dataset
    for expected in (1, 0):
        result = verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
        assert result['samples'] == 1 and result['new_revisions'] == expected
    with factory() as db:
        assert db.query(Document).count() == db.query(Revision).count() == db.query(Snapshot).count() == 1
        doc = db.scalar(select(Document))
        rev = db.get(Revision, doc.current_revision)
        snap = db.get(Snapshot, rev.snapshot_id)
        assert rev.body == parsed['body']
        assert LocalStore(settings.object_root).read('raw/' + snap.raw_sha[:2] + '/' + snap.raw_sha)
        assert snap.method == 'verified-cache'
        assert datetime.fromtimestamp(snap.fetched, timezone.utc).date().isoformat() == '2026-11-01'
        source = db.get(Source, 'sample')
        assert not source.enabled and source.last_success is None


def test_import_corrupt_original_fails_before_database_writes(dataset):
    factory, settings, root, _ = dataset
    (root / 'original.html').write_text('corrupt')
    with pytest.raises(ValueError, match='evidence_hash_mismatch'):
        verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
    with factory() as db:
        assert db.query(Document).count() == 0


def test_cached_import_never_overwrites_newer_live_revision(dataset):
    factory, settings, root, parsed = dataset
    verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
    with factory.begin() as db:
        persist_detail(db, db.get(Source, 'sample'), {**parsed, 'body': 'new live body'},
            LocalStore(settings.object_root).put(b'new live original', 'text/html'), 'https://official.gov.cn/a.html', method='httpx')
    verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
    with factory() as db:
        doc = db.scalar(select(Document))
        assert db.get(Revision, doc.current_revision).body == 'new live body'
        assert db.query(Revision).count() == 2


def test_service_reopens_same_db_without_enabling_unimported_sources(tmp_path):
    root = tmp_path / 'service'
    settings, engine, factory = open_service(root)
    try:
        with pytest.raises(ValueError, match='import_verified_pages_before_activation'):
            enable_verified(factory)
        with factory.begin() as db:
            for source in db.scalars(select(Source)):
                source.checkpoint = {'verified_import': {'samples': 20}}
            db.add(Task(kind='attachment', key='old-attachment', payload={'source_id': 'nhc-policy'}))
            db.add(Task(kind='list', key='new-list', payload={'source_id': 'nhc-policy'}))
        assert enable_verified(factory) == 58
        from policy_v2.queue import claim
        assert claim(factory)['kind'] == 'list', 'Backfill discovery must not wait behind imported attachments'
    finally:
        engine.dispose()
    second, engine, factory = open_service(root)
    try:
        assert second.database_url == settings.database_url
        with factory() as db:
            assert sum(s.enabled for s in db.scalars(select(Source))) == 58
            assert not db.get(Source, 'he-policy')
    finally:
        engine.dispose()


def test_api_distinguishes_unconnected_backfill_no_matches_and_completed(dataset, monkeypatch):
    import policy_v2.app as api
    factory, settings, root, _ = dataset
    monkeypatch.setattr(api, 'SessionLocal', factory)
    verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
    with factory.begin() as db:
        db.get(Source, 'sample').enabled = True
    with TestClient(api.app) as client:
        missing = client.get('/api/v2/policies', params={'region': 'HE', 'include_national': False}).json()
        assert missing['total'] == 0 and missing['scope']['state'] == 'not_connected'
        partial = client.get('/api/v2/policies', params={'region': 'CN'}).json()
        assert partial['total'] == 1 and partial['scope']['state'] == 'backfilling'
        no_matches = client.get('/api/v2/policies', params={'region': 'CN', 'q': 'does-not-exist'}).json()
        assert no_matches['scope']['state'] == 'no_matches'
        with factory.begin() as db:
            db.add(CollectionRun(source_id='sample', bucket=1, state='succeeded', config_hash='test',
                listing_complete=True, pages_read=7, finished=1))
        complete = client.get('/api/v2/coverage').json()[0]
        assert complete['history_state'] == 'complete' and complete['history_pages'] == 7
        assert complete['documents'] == 1


def test_malformed_pdf_text_cannot_break_policy_list_or_detail(dataset, monkeypatch):
    import policy_v2.app as api
    factory, settings, root, _ = dataset
    monkeypatch.setattr(api, 'SessionLocal', factory)
    verified_import.import_verified(factory, settings, root / 'report.json', workspace=root)
    with factory.begin() as db:
        rev = db.scalar(select(Revision))
        rev.attachments = [{'url': 'https://official.gov.cn/a.pdf', 'status': 'ready',
            'extracted': [{'page': 2, 'text': '原件特殊字形\udded'}]}]
        doc_id = rev.document_id
    with TestClient(api.app, raise_server_exceptions=False) as client:
        for url in ('/api/v2/policies?region=CN', f'/api/v2/policies/{doc_id}'):
            response = client.get(url)
            assert response.status_code == 200
            assert '\ufffd' in response.text


def test_pdf_extraction_marks_repaired_unicode_and_keeps_valid_pairs(monkeypatch):
    import pypdf
    from policy_v2.extraction import extract
    page = SimpleNamespace(extract_text=lambda: '坏字\udded与正常字\ud83d\ude00')
    monkeypatch.setattr(pypdf, 'PdfReader', lambda _: SimpleNamespace(pages=[page]))
    blocks, status = extract(b'original unchanged', 'https://official.gov.cn/a.pdf')
    assert status == 'ready' and blocks[0]['unicode_repaired']
    assert blocks[0]['text'] == '坏字\ufffd与正常字😀'
