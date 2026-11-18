import copy
import hashlib
from types import SimpleNamespace

from sqlalchemy import select
from policy_v2 import summaries as ai
from policy_v2.models import Audit, Document, Revision, SummaryRecord, Task, now
from policy_v2.summary_repair import import_bundle, digest
from test_summary_pipeline import env, ingest, BODY, QUOTE


def failed_bundle(env):
    factory, settings = env
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    with factory.begin() as db:
        rev = db.get(Revision, rid); doc = db.get(Document, rev.document_id)
        task = db.scalar(select(Task)); task.state = 'failed'; task.attempts = 3
        rev.summary_status = 'failed'
        content, _ = ai.summary_input(rev)
        points = ai.validate_points({'points': [{'text': '建立医疗质量管理制度。', 'quote': QUOTE, 'source': 'body'}]}, content['segments'])
        item = {'id': doc.id, 'url': doc.url, 'revision': rev.number, 'title': rev.title,
                'published': rev.published, 'body_sha256': digest(rev.body), 'attachment_urls': [], 'media': [],
                'result': {'state': 'ready', 'input_sha': content['sha'], 'model': settings.ai_model,
                           'prompt_version': ai.PROMPT_VERSION, 'generated_at': now(), 'usage': {}, 'points': points}}
    return rid, {'format': 1, 'items': [item]}


def test_repair_is_idempotent_preserves_body_and_other_successes(env):
    factory, settings = env
    rid, bundle = failed_bundle(env)
    other = ingest(env, url='https://official.gov.cn/success')
    with factory.begin() as db:
        db.get(Revision, other).summary_status = 'ready'
        db.get(Revision, other).summary = [{'text': '保持原摘要'}]
    assert import_bundle(factory, settings, bundle)['ready'] == [bundle['items'][0]['id']]
    assert import_bundle(factory, settings, bundle)['already_ready'] == [bundle['items'][0]['id']]
    with factory() as db:
        assert db.get(Revision, rid).body == BODY
        assert db.get(Revision, rid).summary_status == 'ready'
        assert db.get(Revision, other).summary == [{'text': '保持原摘要'}]
        assert db.query(Audit).filter_by(action='summary.repaired').count() == 1
        assert db.get(SummaryRecord, rid).prompt_version == ai.PROMPT_VERSION


def test_source_change_or_fabricated_evidence_never_imports(env):
    factory, settings = env
    rid, bundle = failed_bundle(env)
    bad = copy.deepcopy(bundle); bad['items'][0]['body_sha256'] = '0'*64
    assert import_bundle(factory, settings, bad)['skipped'][0]['reason'] == 'source_changed'
    bad = copy.deepcopy(bundle); bad['items'][0]['result']['points'][0]['quote'] = '原文不存在的虚假证据引句'
    assert import_bundle(factory, settings, bad)['failed']
    with factory() as db:
        assert db.get(Revision, rid).summary_status == 'failed'
        assert db.get(Revision, rid).summary == []


def test_image_bytes_verified_before_summary_and_pending_download_cancelled(env, tmp_path):
    factory, settings = env
    rid, bundle = failed_bundle(env)
    item = bundle['items'][0]
    image = b'fixed source image bytes'; sha = hashlib.sha256(image).hexdigest()
    url = 'https://official.gov.cn/image.jpg'
    media = {'index': 0, 'url': url, 'sha256': sha, 'method': 'test-ocr', 'extracted': [{'page': 1, 'text': BODY}]}
    item['media'] = [media]; item['attachment_urls'] = [url]
    with factory.begin() as db:
        rev = db.get(Revision, rid)
        rev.attachments = [{'name': '正文图片', 'image': True, 'url': url, 'status': 'pending'}]
        db.add(Task(kind='attachment', key='old-image-download', payload={'revision_id': rid, 'url': url}, state='queued'))
        attachments = [dict(rev.attachments[0], status='ready', extracted=media['extracted'])]
        content, _ = ai.summary_input(SimpleNamespace(title=rev.title, body=rev.body, attachments=attachments))
        item['result']['input_sha'] = content['sha']
        item['result']['points'] = ai.validate_points({'points': [{'text': '建立制度', 'quote': QUOTE, 'source': 'attachment:0:0'}]}, content['segments'])
    asset = tmp_path / f"{item['id']}-0"; asset.write_bytes(b'wrong image')
    assert import_bundle(factory, settings, bundle, asset_root=tmp_path)['failed'][0]['reason'] == 'attachment_hash_mismatch'
    asset.write_bytes(image)
    assert import_bundle(factory, settings, bundle, asset_root=tmp_path)['ready'] == [item['id']]
    with factory() as db:
        assert db.get(Revision, rid).attachments[0]['sha256'] == sha
        assert db.scalar(select(Task).where(Task.key == 'old-image-download')).state == 'cancelled'
    assert import_bundle(factory, settings, bundle)['already_ready'] == [item['id']]


def test_retry_old_prompt_schedules_current_prompt_without_model_call(env, monkeypatch):
    factory, settings = env
    rid, _ = failed_bundle(env)
    with factory.begin() as db:
        task = db.scalar(select(Task)); task.payload = dict(task.payload, prompt_version='evidence-v2')
        task.key = 'old-v2-task'
    assert ai.retry_failed(factory) == 1
    monkeypatch.setattr(ai, 'generate', lambda *a: (_ for _ in ()).throw(AssertionError('old prompt must not run')))
    assert ai.process_summary(factory, settings)
    assert ai.schedule_batch(factory, settings) == 1
    with factory() as db:
        record = db.get(SummaryRecord, rid)
        assert record.prompt_version == ai.PROMPT_VERSION
        assert db.get(Task, record.task_id).attempts == 0


def test_audio_must_be_linked_in_original_snapshot_and_keeps_timestamps(env, tmp_path):
    from policy_v2.models import RawObject, Snapshot
    from policy_v2.storage import LocalStore
    factory, settings = env
    rid, bundle = failed_bundle(env); item = bundle['items'][0]
    url = 'https://official.gov.cn/audio.mp3'; data = b'official MP3 bytes'
    patch = {'index': 0, 'url': url, 'append': True, 'kind': 'audio', 'sha256': hashlib.sha256(data).hexdigest(),
             'method': 'test-transcription', 'extracted': [{'text': BODY, 'start_seconds': 0, 'end_seconds': 90}]}
    item['media'] = [patch]
    (tmp_path / f"{item['id']}-0").write_bytes(data)
    with factory.begin() as db:
        rev = db.get(Revision, rid)
        media = [{'url': url, 'name': '官方音频（文字转写）', 'audio': True, 'extracted': patch['extracted']}]
        content, _ = ai.summary_input(SimpleNamespace(title=rev.title, body=rev.body, attachments=media))
        assert content['scope'] == 'body_and_audio'
        item['result']['input_sha'] = content['sha']
        item['result']['points'] = ai.validate_points({'points': [{'text': '建立制度', 'quote': QUOTE, 'source': 'attachment:0:0'}]}, content['segments'])
    result = import_bundle(factory, settings, bundle, asset_root=tmp_path)
    assert result['failed'][0]['reason'] == 'audio_not_in_saved_original'
    with factory.begin() as db:
        rev = db.get(Revision, rid)
        stored = LocalStore(settings.object_root).put(b'<a href="/audio.mp3">official audio</a>', 'text/html')
        db.add(RawObject(**stored)); db.flush()
        db.get(Snapshot, rev.snapshot_id).raw_sha = stored['sha']
    assert import_bundle(factory, settings, bundle, asset_root=tmp_path)['ready'] == [item['id']]
    assert import_bundle(factory, settings, bundle)['already_ready'] == [item['id']]
    with factory() as db:
        assert db.get(Revision, rid).summary[0]['location'] == {'start_seconds': 0, 'end_seconds': 90}


def test_unchanged_media_download_preserves_verified_ocr(env, monkeypatch):
    from policy_v2.pipeline import process_one
    factory, settings = env
    rid = ingest(env)
    raw = b'original image'; sha = hashlib.sha256(raw).hexdigest(); url = 'https://official.gov.cn/image.jpg'
    with factory.begin() as db:
        rev = db.get(Revision, rid)
        rev.attachments = [{'name': '正文图片', 'url': url, 'image': True, 'status': 'ready',
                            'sha256': sha, 'extraction_method': 'verified-ocr', 'extracted': [{'text': BODY}]}]
        db.add(Task(kind='attachment', key='refresh-image', payload={'revision_id': rid, 'source_id': 'test', 'url': url}))
    monkeypatch.setattr('policy_v2.pipeline.extract', lambda *a: ([], 'needs_ocr'))
    fetcher = SimpleNamespace(get=lambda *a, **k: (raw, 'image/jpeg', url))
    assert process_one(factory, settings, fetcher=fetcher)
    with factory() as db:
        attachment = db.get(Revision, rid).attachments[0]
        assert attachment['status'] == 'ready' and attachment['extracted'] == [{'text': BODY}]
