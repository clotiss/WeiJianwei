import json
from datetime import date
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event, Lock, Thread
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from policy_v2.db import Base, database
from policy_v2.models import Source, Document, Revision, Task, SummaryRecord, SummaryProviderState, RunTask, now
from policy_v2.settings import Settings
from policy_v2.ingestion import persist_detail
from policy_v2.storage import LocalStore
from policy_v2 import summaries as ai
from policy_v2.queue import claim
from policy_v2.pipeline import process_one

BODY = '各医疗机构应当建立医疗质量管理制度，完善诊疗规范，强化人员培训，保障患者安全。' * 4
QUOTE = '各医疗机构应当建立医疗质量管理制度'

@pytest.fixture
def env(tmp_path, monkeypatch):
    window = ai.summary_window(date(2026, 11, 18))
    monkeypatch.setattr(ai, 'summary_window', lambda: window)
    settings=Settings(database_url='sqlite:///'+str(tmp_path/'test.db'),object_root=tmp_path/'objects',ai_key='test-secret')
    engine,factory=database(settings.database_url);Base.metadata.create_all(engine)
    with factory.begin() as db:
        db.add(Source(id='test',name='official',region='CN',kind='policy',url='https://official.gov.cn/list',enabled=True,config={'hosts':['official.gov.cn']}))
    yield factory,settings
    engine.dispose()

def ingest(env, body=BODY, url='https://official.gov.cn/a', **extra):
    factory,settings=env
    with factory.begin() as db:
        _,rev,_=persist_detail(db,db.get(Source,'test'),dict(title='医疗质量通知',body=body,published='2026-11-17',
            authority='卫健委',doc_number='',kind='policy',attachments=[],**extra),
            LocalStore(settings.object_root).put(body.encode(),'text/html'),url,method='httpx')
        return rev.id

def response(points=None, status=200, **kwargs):
    return httpx.Response(status,json={'choices':[{'finish_reason':'stop','message':{'content':json.dumps({'points':points if points is not None else [{'text':'建立医疗质量管理制度。','quote':QUOTE,'source':'body'}]},ensure_ascii=False)}}],
        'usage':{'prompt_tokens':200,'completion_tokens':60,'total_tokens':260}},**kwargs)

def due(factory):
    with factory.begin() as db:
        for task in db.scalars(select(Task).where(Task.kind=='summary')):task.available=0
        provider=db.get(SummaryProviderState,1)
        if provider:provider.cooldown_until=0

def test_three_calendar_year_window_and_leap_day():
    assert ai.summary_window(date(2026, 11, 18)) == (date(2023, 11, 18), date(2026, 11, 18))
    assert ai.summary_window(date(2024, 2, 29))[0] == date(2021, 2, 28)

def test_ten_parallel_summaries_are_unique_and_shutdown_drains_inflight(env, monkeypatch):
    factory, settings = env
    assert settings.ai_concurrency == 10
    for index in range(12):
        ingest(env, url=f'https://official.gov.cn/{index}')
    entered, release, stop, lock = Event(), Event(), Event(), Lock()
    calls, errors = [], []
    def generate(settings, content):
        with lock:
            calls.append(content['sha'])
            if len(calls) == 10: entered.set()
        assert release.wait(10)
        return ai.validate_points({'points': [{'text': '建立制度', 'quote': QUOTE, 'source': 'body'}]}, content['segments']), {}
    monkeypatch.setattr(ai, 'generate', generate)
    def run():
        try: ai.run_summary_worker(factory, settings, stop)
        except BaseException as exc: errors.append(exc)
    worker = Thread(target=run)
    worker.start()
    try:
        assert entered.wait(10), errors
        with factory() as db:
            running = list(db.scalars(select(Task).where(Task.state == 'running')))
            assert len(running) == 10
            assert len({task.payload['revision_id'] for task in running}) == 10
    finally:
        stop.set(); release.set(); worker.join(10)
    assert not worker.is_alive() and not errors and len(calls) == 10
    with factory() as db:
        tasks = list(db.scalars(select(Task)))
        assert sum(task.state == 'succeeded' for task in tasks) == 10
        assert sum(task.state == 'queued' for task in tasks) == 2
        assert all(task.attempts <= 1 for task in tasks)
        assert db.query(Revision).filter_by(summary_status='ready').count() == 10

def test_concurrent_provider_failures_keep_longest_shared_pause(env, monkeypatch):
    factory, settings = env
    for index in range(3): ingest(env, url=f'https://official.gov.cn/{index}')
    ai.schedule_batch(factory, settings)
    barrier, lock, statuses = Barrier(2), Lock(), [402, 429]
    def post(*args, **kwargs):
        with lock: status = statuses.pop()
        barrier.wait(5)
        return response(status=status)
    monkeypatch.setattr(ai.httpx, 'post', post)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [pool.submit(ai.process_summary, factory, settings) for _ in range(2)]
        assert all(result.result(timeout=10) for result in results)
    assert not ai.process_summary(factory, settings)
    with factory() as db:
        provider = db.get(SummaryProviderState, 1)
        assert provider.error == 'quota_exhausted' and provider.cooldown_until > now()+3500
        tasks = list(db.scalars(select(Task)))
        assert sorted(task.attempts for task in tasks) == [0, 1, 1]
        assert all(task.state == 'queued' for task in tasks)

@pytest.mark.parametrize('published,eligible,state', [
    ('2023-11-17', False, 'outside_summary_window'),
    ('2023-11-18', True, 'queued'),
    ('2026-11-18', True, 'queued'),
    ('2026-11-19', False, 'outside_summary_window'),
    (None, False, 'publication_date_unknown'),
    ('2026-02-30', False, 'publication_date_unknown'),
])
def test_summary_date_boundaries_keep_documents_searchable(env, published, eligible, state):
    factory, settings = env
    rid = ingest(env)
    with factory.begin() as db:
        db.get(Revision, rid).published = published
    assert ai.schedule_batch(factory, settings) == int(eligible)
    with factory() as db:
        rev = db.get(Revision, rid)
        assert ai.summary_view(db, rev, settings)['state'] == state
        assert db.get(Document, rev.document_id).status == 'ready'
        assert db.query(Task).count() == int(eligible)

def test_old_queued_jobs_cancel_during_quota_pause_without_attempts(env):
    factory, settings = env
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    with factory.begin() as db:
        db.get(Revision, rid).published = '2020-01-01'
        db.add(SummaryProviderState(id=1, cooldown_until=now()+3600, error='quota_exhausted'))
    assert ai.schedule_batch(factory, settings) == 0
    assert not ai.process_summary(factory, settings)
    with factory() as db:
        task = db.scalar(select(Task))
        assert task.state == 'cancelled' and task.attempts == 0
        assert ai.summary_view(db, db.get(Revision, rid), settings)['state'] == 'outside_summary_window'
    assert ai.retry_failed(factory) == 0

def test_worker_rechecks_existing_jobs_before_external_request(env, monkeypatch):
    factory, settings = env
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    with factory.begin() as db:
        db.get(Revision, rid).published = '2020-01-01'
    monkeypatch.setattr(ai, 'generate', lambda *args: pytest.fail('old policy must not call AI'))
    assert ai.process_summary(factory, settings)
    with factory() as db:
        assert db.get(Revision, rid).summary_status == 'outside_summary_window'
        assert db.get(Revision, rid).summary == []

def test_saved_old_summaries_are_preserved(env, monkeypatch):
    factory, settings = env
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    monkeypatch.setattr(ai.httpx, 'post', lambda *args, **kwargs: response())
    ai.process_summary(factory, settings)
    with factory.begin() as db:
        db.get(Revision, rid).published = '2020-01-01'
    ai.schedule_batch(factory, settings)
    with factory() as db:
        rev = db.get(Revision, rid)
        assert rev.summary and ai.summary_view(db, rev, settings)['state'] == 'ready'

def test_corrected_date_reactivates_cancelled_job(env):
    factory, settings = env
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    with factory.begin() as db:
        db.get(Revision, rid).published = '2020-01-01'
    ai.schedule_batch(factory, settings)
    with factory.begin() as db:
        db.get(Revision, rid).published = '2026-11-17'
    assert ai.schedule_batch(factory, settings) == 1
    with factory() as db:
        assert db.query(Task).count() == 1
        assert db.scalar(select(Task)).state == 'queued'

@pytest.mark.parametrize('endpoint,nonthinking', [
    ('https://api.deepseek.com/v1/chat/completions', True),
    ('https://other.example/v1/chat/completions', False),
])
def test_v4_summary_finishes_with_small_output_budget(env, monkeypatch, endpoint, nonthinking):
    factory, settings = env
    settings.ai_model = 'deepseek-v4-pro'
    settings.ai_url = endpoint
    rid = ingest(env)
    ai.schedule_batch(factory, settings)
    def post(*args, **kwargs):
        request = kwargs['json']
        if nonthinking and request.get('thinking') != {'type': 'disabled'}:
            return httpx.Response(200, json={'choices': [{'finish_reason': 'length', 'message': {'content': ''}}]})
        if not nonthinking:
            assert 'thinking' not in request
        return response()
    monkeypatch.setattr(ai.httpx, 'post', post)
    assert ai.process_summary(factory, settings)
    with factory() as db:
        assert db.get(Revision, rid).summary_status == 'ready'

def test_new_and_historical_revisions_dedupe_persist_and_expose_evidence(env,monkeypatch):
    factory,settings=env;rid=ingest(env)
    assert ai.schedule_batch(factory,settings)==1
    assert ai.schedule_batch(factory,settings)==0
    calls=[]
    def post(*args,**kwargs):calls.append(kwargs);return response()
    monkeypatch.setattr(ai.httpx,'post',post)
    assert ai.process_summary(factory,settings)
    with factory() as db:
        rev=db.get(Revision,rid);record=db.get(SummaryRecord,rid)
        assert rev.summary_status=='ready' and record.generated and record.usage['total_tokens']==260
        point=rev.summary[0];assert rev.body[point['start']:point['end']]==point['quote']
        assert db.query(RunTask).count()==0
        doc_id=rev.document_id
    assert not ai.process_summary(factory,settings)
    assert ingest(env)==rid
    assert ai.schedule_batch(factory,settings)==0
    # A changed original creates a new task; the previous revision stays unchanged.
    second=ingest(env,BODY+'新要求：完善随访制度。')
    assert second!=rid and ai.schedule_batch(factory,settings)==1
    assert ai.process_summary(factory,settings)
    assert len(calls)==2
    import policy_v2.app as api
    monkeypatch.setattr(api,'SessionLocal',factory);monkeypatch.setattr(api,'settings',settings)
    with TestClient(api.app) as client:
        item=client.get(f'/api/v2/policies/{doc_id}').json()
        assert item['summary_status']['state']=='ready' and item['summary'][0]['quote']==QUOTE
        assert client.get('/api/v2/policies').json()['items'][0]['summary_status']['state']=='ready'

@pytest.mark.parametrize('point',[
    {'text':'伪造结论','quote':'这句话不在原文中但长度足够','source':'body'},
    {'text':'','quote':QUOTE,'source':'body'},
    {'text':'测试','quote':QUOTE,'source':'missing'},
    {'text':'测试','quote':12,'source':'body'},
])
def test_invalid_evidence_is_never_published_and_retries_are_bounded(env,monkeypatch,point):
    factory,settings=env;rid=ingest(env);ai.schedule_batch(factory,settings)
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:response([point]))
    for attempt in range(3):
        due(factory);assert ai.process_summary(factory,settings)
        with factory() as db:
            rev=db.get(Revision,rid);task=db.scalar(select(Task))
            assert rev.summary==[] and task.attempts==attempt+1
            assert rev.summary_status==('failed' if attempt==2 else 'retrying')
    assert not ai.process_summary(factory,settings)
    assert ai.retry_failed(factory)==1
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:response())
    assert ai.process_summary(factory,settings)
    with factory() as db:assert db.get(Revision,rid).summary_status=='ready'

@pytest.mark.parametrize('status,code',[(401,'authentication_failed'),(402,'quota_exhausted'),(429,'rate_limited'),(503,'provider_unavailable')])
def test_provider_cooldown_stops_all_requests_without_affecting_collector(env,monkeypatch,status,code):
    factory,settings=env;rid=ingest(env);ingest(env,url='https://official.gov.cn/b');ai.schedule_batch(factory,settings)
    calls=[]
    def post(*a,**k):calls.append(1);return response(status=status,headers={'Retry-After':'120'})
    monkeypatch.setattr(ai.httpx,'post',post)
    assert ai.process_summary(factory,settings)
    assert not ai.process_summary(factory,settings) and len(calls)==1
    with factory.begin() as db:
        provider=db.get(SummaryProviderState,1);assert provider.error==code and provider.cooldown_until>now()
        assert ai.summary_view(db,db.get(Revision,rid),settings)['state']=='service_paused'
        db.add(Task(kind='detail',key='collector',payload={},priority=99))
        assert db.get(Source,'test').last_error==''
    assert claim(factory,kinds=('detail',))['kind']=='detail'
    with factory() as db:assert all(settings.ai_key not in t.error for t in db.scalars(select(Task)))

def test_no_key_no_cost_and_explicit_state(env):
    factory,settings=env;rid=ingest(env);settings.ai_key=''
    assert ai.schedule_batch(factory,settings)==0 and not ai.process_summary(factory,settings)
    with factory() as db:
        assert db.query(Task).count()==0
        assert ai.summary_view(db,db.get(Revision,rid),settings)['state']=='not_configured'

def test_collector_never_consumes_summary_jobs(env):
    factory,settings=env;ingest(env);ai.schedule_batch(factory,settings)
    assert not process_one(factory,settings,fetcher=object())
    with factory() as db:assert db.scalar(select(Task)).attempts==0

def test_short_video_and_pending_attachment_skip_model(env):
    factory,settings=env;rid=ingest(env,'视频解读')
    ai.schedule_batch(factory,settings)
    with factory.begin() as db:
        rev=db.get(Revision,rid);assert rev.summary_status=='insufficient_content'
        rev.summary_status='pending';rev.attachments=[{'status':'pending','url':'https://official.gov.cn/a.pdf'}]
    ai.schedule_batch(factory,settings)
    with factory() as db:assert db.get(Revision,rid).summary_status=='waiting_content' and db.query(Task).count()==0

def test_attachment_text_is_locatable_and_long_body_is_explicitly_partial():
    content,_=ai.summary_input(SimpleNamespace(body='',title='附件',attachments=[{'name':'办法.pdf','url':'https://official.gov.cn/a.pdf','status':'ready','extracted':[{'page':2,'text':BODY}]}]))
    point=ai.validate_points({'points':[{'text':'建立制度','quote':QUOTE,'source':'attachment:0:0'}]},content['segments'])[0]
    assert point['location']=={'page':2} and point['source_name']=='办法.pdf' and content['scope']=='attachments'
    content,_=ai.summary_input(SimpleNamespace(body=BODY*1000,title='长文',attachments=[]))
    assert content['chars']==ai.MAX_CHARS and content['scope']=='body_excerpt'


def test_html_inline_linebreaks_restore_literal_evidence_offsets():
    raw = '通知：要求任职前接受不少于\n8\n学时的系统培训。'
    source = {'id': 'body', 'text': raw, 'name': '正文', 'url': '', 'location': {}}
    result = {'points': [{'text': '任职前培训不少于8学时',
                         'quote': '要求任职前接受不少于8学时的系统培训', 'source': 'body'}]}
    point = ai.validate_points(result, [source])[0]
    assert point['quote'] == '要求任职前接受不少于\n8\n学时的系统培训'
    assert raw[point['start']:point['end']] == point['quote']
    for false_quote in ('要求任职前接受不少于80学时的系统培训',
                        '要求任职前接受不多于8学时的系统培训',
                        '要求任职后接受不少于8学时的系统培训'):
        result['points'][0]['quote'] = false_quote
        with pytest.raises(ai.SummaryError, match='evidence_mismatch'):
            ai.validate_points(result, [source])


def test_numbered_evidence_uses_original_source_and_rejects_invented_id(env, monkeypatch):
    factory, settings = env
    raw = '要求任职前接受不少于\n8\n学时的系统培训。' * 80
    content, _ = ai.summary_input(SimpleNamespace(body=raw, title='培训要求', attachments=[]))
    candidates = ai.evidence_candidates(content['segments'])
    assert len(candidates) > 1 and all(len(c['text']) <= 1200 for c in candidates)
    for c in candidates:
        assert raw[c['start']:c['start'] + len(c['text'])] == c['text']
    def post(*args, **kwargs):
        payload = json.loads(kwargs['json']['messages'][1]['content'])
        assert payload['segments'][1]['id'] == candidates[1]['id']
        return response([{'text': '任职前培训不少于8学时。', 'evidence_id': candidates[1]['id']}])
    monkeypatch.setattr(ai.httpx, 'post', post)
    points, _ = ai.generate(settings, content)
    assert points[0]['quote'] == candidates[1]['text']
    assert raw[points[0]['start']:points[0]['end']] == points[0]['quote']
    monkeypatch.setattr(ai.httpx, 'post', lambda *a, **k: response([{'text': '伪造引用', 'evidence_id': 'e999999'}]))
    with pytest.raises(ai.SummaryError, match='evidence_mismatch'): ai.generate(settings, content)


def test_image_text_is_included_even_when_related_link_titles_exceed_minimum():
    body = '相关链接：' + '中医药产业高质量发展政策解读' * 8
    content, _ = ai.summary_input(SimpleNamespace(body=body, title='政策图解', attachments=[
        {'name': '正文图片', 'url': 'https://official.gov.cn/image.jpg', 'image': True,
         'status': 'ready', 'extracted': [{'page': 1, 'text': BODY}]}]))
    assert content['scope'] == 'body_and_images'
    assert content['segments'][1]['text'] == BODY
    assert content['segments'][1]['location'] == {'page': 1}

def test_worker_restart_recovers_expired_lease(env,monkeypatch):
    factory,settings=env;rid=ingest(env);ai.schedule_batch(factory,settings)
    lost=claim(factory,clock=1,kinds=('summary',))
    # Claim at an actual current clock, then simulate process death.
    if not lost:lost=claim(factory,kinds=('summary',))
    with factory.begin() as db:
        db.get(Task,lost['id']).lease_until=0
        db.get(Revision,rid).summary_status='generating'
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:response())
    assert ai.process_summary(factory,settings)
    with factory() as db:assert db.get(Revision,rid).summary_status=='ready'

def test_superseded_revision_is_skipped_and_manual_classification_preserved(env,monkeypatch):
    factory,settings=env;rid=ingest(env);ai.schedule_batch(factory,settings)
    newer=ingest(env,BODY+'补充要求');ai.schedule_batch(factory,settings)
    with factory.begin() as db:
        r=db.get(Revision,newer);r.human_locked=True;r.topic='人工分类';r.classification_status='reviewed'
    calls=[]
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:(calls.append(1) or response()))
    assert ai.process_summary(factory,settings) and ai.process_summary(factory,settings)
    assert len(calls)==1
    with factory() as db:
        assert db.get(Revision,newer).topic=='人工分类'
        assert db.get(Revision,rid).summary==[]

def test_changed_attachment_input_is_requeued_without_stale_result(env,monkeypatch):
    factory,settings=env;rid=ingest(env,'附件')
    with factory.begin() as db:
        r=db.get(Revision,rid);r.attachments=[{'status':'ready','extracted':[{'text':BODY}]}]
    ai.schedule_batch(factory,settings)
    with factory.begin() as db:
        db.get(Revision,rid).attachments=[{'status':'ready','extracted':[{'text':BODY+'更新'}]}]
    assert ai.process_summary(factory,settings) # no external call for stale input
    assert ai.schedule_batch(factory,settings)==1
    with factory() as db:assert db.get(Revision,rid).summary_status=='queued'

def test_timeout_retries_then_recovers_and_never_logs_key(env,monkeypatch):
    factory,settings=env;rid=ingest(env);ai.schedule_batch(factory,settings)
    def timeout(*a,**k):raise httpx.ReadTimeout('secret='+settings.ai_key)
    monkeypatch.setattr(ai.httpx,'post',timeout)
    assert ai.process_summary(factory,settings)
    with factory() as db:
        task=db.scalar(select(Task));assert task.error=='timeout' and task.state=='queued'
        assert db.get(Revision,rid).summary_status=='retrying'
    due(factory);monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:response())
    assert ai.process_summary(factory,settings)
    with factory() as db:assert db.get(Revision,rid).summary_status=='ready'


def test_attachment_download_wakes_waiting_summary(env,monkeypatch):
    factory,settings=env;rid=ingest(env,'查看附件')
    with factory.begin() as db:
        db.get(Revision,rid).attachments=[{'status':'pending','url':'https://official.gov.cn/a.pdf'}]
        db.add(Task(kind='attachment',key='pdf',payload={'revision_id':rid,'source_id':'test','url':'https://official.gov.cn/a.pdf'}))
    ai.schedule_batch(factory,settings)
    monkeypatch.setattr('policy_v2.pipeline.extract',lambda *a:([{'page':1,'text':BODY}],'ready'))
    fetcher=SimpleNamespace(get=lambda url,*a,**k:(b'PDF','application/pdf',url))
    assert process_one(factory,settings,fetcher=fetcher)
    assert ai.schedule_batch(factory,settings)==1
    with factory() as db:assert db.get(SummaryRecord,rid).scope=='attachments'


def test_cached_success_after_crash_is_finished_without_second_api_call(env,monkeypatch):
    factory,settings=env;rid=ingest(env);ai.schedule_batch(factory,settings)
    monkeypatch.setattr(ai.httpx,'post',lambda *a,**k:response())
    assert ai.process_summary(factory,settings)
    with factory.begin() as db:
        task=db.scalar(select(Task));task.state='running';task.owner='dead';task.lease_until=0
    def forbidden(*a,**k):pytest.fail('successful result must be reused after restart')
    monkeypatch.setattr(ai.httpx,'post',forbidden)
    assert ai.process_summary(factory,settings)
    with factory() as db:assert db.scalar(select(Task)).state=='succeeded'

def test_citation_offsets_preserve_leading_whitespace_and_blank_body_is_not_evidence():
    body=' \n  '+BODY
    content,_=ai.summary_input(SimpleNamespace(body=body,title='通知',attachments=[]))
    point=ai.validate_points({'points':[{'text':'建立制度','quote':QUOTE,'source':'body'}]},content['segments'])[0]
    assert body[point['start']:point['end']]==QUOTE
    content,state=ai.summary_input(SimpleNamespace(body=' \n'*100,title='空文',attachments=[]))
    assert content is None and state=='insufficient_content'
