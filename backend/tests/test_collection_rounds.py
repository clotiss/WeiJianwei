"""Exercise monitoring through the real scheduler, queue, parser and persistence."""
from urllib.parse import urlsplit, parse_qs

import pytest
from policy_v2.db import Base, database
from policy_v2.models import Source, Task, Document, Revision, CollectionRun, TaskRepair, Attempt, Audit
from policy_v2.network import FetchError
from policy_v2.pipeline import discover, process_one
from policy_v2.settings import Settings


@pytest.fixture
def env(tmp_path):
    engine, factory = database('sqlite:///' + str(tmp_path / 'rounds.db'))
    Base.metadata.create_all(engine)
    with factory.begin() as db:
        db.add(Source(id='test', name='Official source', region='CN', kind='policy',
            url='https://official.gov.cn/list?page=1', enabled=True, last_success=1000,
            config={'hosts':['official.gov.cn'], 'list_selector':'li', 'next_selector':'a.next',
                    'body_selectors':['article'], 'max_pages':2}))
    yield factory, Settings(object_root=tmp_path / 'objects', task_max_attempts=1, source_cooldown_seconds=0)
    engine.dispose()


class Site:
    def __init__(self, pages=1, attachment=False):
        self.pages = pages
        self.attachment = attachment
        self.fail_attachment = False
        self.calls = []

    def get(self, url, hosts, **kwargs):
        self.calls.append(url)
        if '/list?' in url:
            page = int(parse_qs(urlsplit(url).query)['page'][0])
            text = f'<li>2026-11-17<a href="/document-{page}.html">Official policy number {page}</a></li>'
            if page < self.pages:
                text += f'<a class="next" href="/list?page={page+1}">Next</a>'
        elif url.endswith('.docx'):
            if self.fail_attachment:
                raise FetchError('http_503')
            return b'attachment bytes', 'application/octet-stream', url
        else:
            text = '<article>This is a complete public policy document with sufficient body text for validation.'
            if self.attachment:
                text += '<a href="/attachment.docx">Original attachment</a>'
            text += '</article>'
        return text.encode(), 'text/html', url


def drain(factory, settings, site):
    for _ in range(100):
        if not process_one(factory, settings, fetcher=site):
            return
    pytest.fail('worker did not become idle')


def test_pagination_continues_after_batch_limit_and_scheduler_restart(env):
    factory, settings = env
    site = Site(pages=5)
    for _ in range(4):
        discover(factory, 'test')
        drain(factory, settings, site)
        # Each discover uses a new DB session, as after a scheduler restart.
    with factory() as db:
        assert db.query(Document).count() == 5
        assert db.get(Source, 'test').last_success > 1000


def test_list_success_does_not_report_a_complete_round(env):
    factory, settings = env
    discover(factory, 'test')
    assert process_one(factory, settings, fetcher=Site())
    with factory() as db:
        assert db.query(Task).filter_by(kind='detail', state='queued').count() == 1
        assert db.get(Source, 'test').last_success == 1000


def test_exhausted_attachment_is_repaired_without_a_new_revision(env, monkeypatch):
    factory, settings = env
    monkeypatch.setattr('policy_v2.pipeline.extract', lambda *a: ([{'text':'Extracted attachment'}], 'ready'))
    site = Site(attachment=True)
    site.fail_attachment = True
    discover(factory, 'test')
    drain(factory, settings, site)
    with factory.begin() as db:
        task = db.query(Task).filter_by(kind='attachment').one()
        assert task.state == 'failed'
        task.available = 0  # Simulate the durable repair delay elapsing.
        source = db.get(Source, 'test')
        source.checkpoint = {**source.checkpoint, 'cooldown_until':0}
    site.fail_attachment = False
    discover(factory, 'test')
    drain(factory, settings, site)
    with factory() as db:
        assert db.query(Revision).count() == 1
        assert db.query(Revision).one().attachments[0]['status'] == 'ready'
        assert db.get(Source, 'test').last_success > 1000


def test_completed_sweep_finds_new_items_beyond_old_window_and_deduplicates(env, monkeypatch):
    import time
    factory, settings = env
    site = Site(pages=2)
    discover(factory,'test');drain(factory,settings,site)
    later=time.time()+21600
    monkeypatch.setattr('policy_v2.rounds.time.time',lambda:later)
    site.pages=6
    for _ in range(4):
        discover(factory,'test');drain(factory,settings,site)
    with factory() as db:
        assert db.query(Document).count()==db.query(Revision).count()==6
        runs=db.query(CollectionRun).order_by(CollectionRun.id).all()
        assert len(runs)==2 and all(r.state=='succeeded' for r in runs)
        assert runs[-1].pages_read==6


def test_two_schedulers_only_create_one_run(env):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    factory,_=env
    barrier=Barrier(2)
    def schedule(_):
        barrier.wait()
        return discover(factory,'test')
    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(schedule,range(2)))==1
    with factory() as db:
        assert db.query(CollectionRun).count()==db.query(Task).count()==1


@pytest.mark.parametrize('mode',['cycle','limit'])
def test_incomplete_pagination_cannot_be_reported_as_success(env,mode):
    factory,settings=env
    if mode=='limit':settings.max_scan_pages=2
    class BrokenSite(Site):
        def get(self,url,hosts,**kwargs):
            data,mime,final=super().get(url,hosts,**kwargs)
            if mode=='cycle' and url.endswith('page=2'):
                data=data.replace(b'page=3',b'page=1')
            return data,mime,final
    site=BrokenSite(pages=5)
    for _ in range(3):
        discover(factory,'test',settings);drain(factory,settings,site)
    with factory() as db:
        run=db.query(CollectionRun).one()
        assert run.state=='blocked' and not run.listing_complete
        assert run.stop_reason==('pagination_cycle' if mode=='cycle' else 'scan_page_limit')
        assert db.get(Source,'test').last_success==1000
    if mode=='limit':
        settings.max_scan_pages=10
        for _ in range(3):
            discover(factory,'test',settings);drain(factory,settings,site)
        with factory() as db:assert db.query(CollectionRun).one().state=='succeeded'


def test_pause_keeps_pending_tasks_and_resumes_without_false_success(env):
    factory,settings=env
    site=Site()
    discover(factory,'test')
    with factory.begin() as db:db.get(Source,'test').enabled=False
    process_one(factory,settings,fetcher=site)
    with factory.begin() as db:
        assert db.query(Task).one().state=='queued'
        assert db.query(CollectionRun).one().state=='paused'
        assert db.get(Source,'test').last_success==1000
        db.get(Source,'test').enabled=True
        db.query(Task).one().available=0
    drain(factory,settings,site)
    with factory() as db:assert db.query(CollectionRun).one().state=='succeeded'


def test_retry_budget_and_admin_retry_are_durable_and_audited(env,monkeypatch):
    from fastapi.testclient import TestClient
    from policy_v2 import app as api
    factory,settings=env
    settings.repair_max_cycles=1
    site=Site(attachment=True);site.fail_attachment=True
    discover(factory,'test',settings);drain(factory,settings,site)
    for _ in range(2):
        with factory.begin() as db:db.query(Task).filter_by(kind='attachment').one().available=0
        discover(factory,'test',settings);drain(factory,settings,site)
    with factory() as db:
        task=db.query(Task).filter_by(kind='attachment').one();task_id=task.id
        assert task.state=='failed' and db.get(TaskRepair,task_id).cycles==1
        assert db.query(Attempt).filter_by(task_id=task_id,status='failed').count()==2
        assert db.query(CollectionRun).one().state=='blocked'
    monkeypatch.setattr(api,'SessionLocal',factory)
    monkeypatch.setattr(api,'settings',settings)
    settings.admin_token='trial-test-token'
    with TestClient(api.app) as client:
        path=f'/api/v2/admin/tasks/{task_id}/retry?reason=operator+verified+site+recovery'
        assert client.post(path).status_code==401
        assert client.post(path,headers={'Authorization':'Bearer trial-test-token'}).status_code==200
        assert client.post(path,headers={'Authorization':'Bearer trial-test-token'}).status_code==409
    site.fail_attachment=False
    monkeypatch.setattr('policy_v2.pipeline.extract',lambda *a:([],'needs_ocr'))
    drain(factory,settings,site)
    with factory() as db:
        assert db.query(CollectionRun).one().state=='succeeded'
        assert db.query(Revision).one().attachments[0]['status']=='needs_ocr'
        assert db.query(Audit).filter_by(action='task.retry').count()==1


def test_later_poll_still_depends_on_previous_failed_attachment(env,monkeypatch):
    import time
    factory,settings=env
    site=Site(attachment=True);site.fail_attachment=True
    discover(factory,'test');drain(factory,settings,site)
    later=time.time()+21600
    monkeypatch.setattr('policy_v2.rounds.time.time',lambda:later)
    # Keep recovery postponed to show that a newer poll cannot hide its failure.
    with factory.begin() as db:db.query(Task).filter_by(kind='attachment').one().available=later+86400
    discover(factory,'test');drain(factory,settings,site)
    with factory() as db:
        assert db.query(Revision).count()==1
        assert db.query(CollectionRun).count()==2
        assert all(r.state=='repairing' for r in db.query(CollectionRun))
        assert db.get(Source,'test').last_success==1000


def test_busy_inflight_domain_is_rechecked_without_waiting_entire_lease(env,monkeypatch):
    import time
    from policy_v2.domains import acquire,release
    from policy_v2.network import SafeFetcher
    factory,settings=env
    owner=acquire(factory,'official.gov.cn',seconds=300)
    fetcher=SafeFetcher(settings,factory)
    monkeypatch.setattr(fetcher,'validate',lambda *a:'official.gov.cn')
    monkeypatch.setattr(fetcher,'_get',lambda *a,**k:pytest.fail('busy domain must not be requested'))
    discover(factory,'test')
    before=time.time()
    process_one(factory,settings,fetcher=fetcher)
    with factory() as db:
        task=db.query(Task).one()
        assert task.state=='queued' and task.attempts==0
        assert task.available<=before+5
    release(factory,'official.gov.cn',owner,0)


def test_upgrade_keeps_failure_visible_for_already_queued_legacy_tasks(env):
    from policy_v2.queue import enqueue
    factory,settings=env
    with factory.begin() as db:
        enqueue(db,'list','legacy-task',{'source_id':'test','url':'https://official.gov.cn/list?page=1','bucket':0})
    class OfflineSite:
        def get(self,*a,**k):raise FetchError('http_503')
    process_one(factory,settings,fetcher=OfflineSite())
    with factory() as db:
        assert db.query(CollectionRun).count()==0
        assert 'http_503' in db.get(Source,'test').last_error
        assert db.get(Source,'test').last_success==1000


def test_official_legacy_office_file_misnamed_docx_is_retained_as_unsupported():
    import gzip,hashlib,zipfile
    from pathlib import Path
    from policy_v2.extraction import extract
    data=gzip.decompress((Path(__file__).parent/'fixtures/bj-misnamed-office.docx.gz').read_bytes())
    assert hashlib.sha256(data).hexdigest()=='751eb3f2d842aed8ef9fb61947bfb993ec57c02db49af85f81ecbc28dc81500e'
    assert extract(data,'https://wjw.beijing.gov.cn/zwgk_20040/zcwj2024/202507/P020250725403442447402.docx')==([],'unsupported')
    with pytest.raises(zipfile.BadZipFile):extract(b'truncated or invalid download','https://official.gov.cn/file.docx')
