import time
from email.utils import formatdate

import pytest

from policy_v2.db import Base, database
from policy_v2.models import Document, Revision, Source, Task, Snapshot
from policy_v2.network import FetchError, SafeFetcher, retry_after_seconds
from policy_v2.pipeline import discover, process_one
from policy_v2.queue import enqueue
from policy_v2.settings import Settings
from policy_v2.source_health import cooldown_until
from policy_v2.sources import seed


@pytest.fixture
def factory(tmp_path):
    engine, sessions = database(f"sqlite:///{tmp_path / 'resilience.db'}")
    Base.metadata.create_all(engine)
    seed(sessions)
    yield sessions
    engine.dispose()


def test_failure_cools_sibling_column_without_losing_history_and_recovers(factory, tmp_path):
    with factory.begin() as db:
        for sid in ('nhc-policy', 'nhc-interpretation'):
            db.get(Source, sid).enabled = True
        source = db.get(Source, 'nhc-policy')
        source.last_success = 1000
        doc = Document(source_id=source.id, url='https://www.nhc.gov.cn/history.shtml', region='CN', status='ready')
        db.add(doc); db.flush()
        rev = Revision(document_id=doc.id, number=1, fingerprint='history', title='Stored policy', body='Stored body', kind='policy')
        db.add(rev); db.flush(); doc.current_revision = rev.id
    for sid in ('nhc-policy', 'nhc-interpretation'):
        discover(factory, sid)
    class Fetcher:
        calls = 0
        last_mode = 'firefox'
        failing = True
        def get(self, url, hosts, **kwargs):
            self.calls += 1
            if self.failing:
                raise FetchError('http_429', retry_after=600)
            return b'<ul class="zxxx_list"><li>2026-11-17 <a href="/new.shtml">New official policy title</a></li></ul>', 'text/html', url
    fetcher = Fetcher()
    settings = Settings(object_root=tmp_path / 'objects')
    before = time.time()
    assert process_one(factory, settings, fetcher=fetcher)
    assert process_one(factory, settings, fetcher=fetcher)
    assert fetcher.calls == 1  # second column deferred without another site request
    with factory() as db:
        sources = [db.get(Source, sid) for sid in ('nhc-policy', 'nhc-interpretation')]
        assert all(cooldown_until(s) >= before + 600 for s in sources)
        assert sources[0].last_success == 1000
        tasks = db.query(Task).order_by(Task.id).all()
        assert [t.attempts for t in tasks] == [1, 0]
        assert all(t.state == 'queued' and t.available >= before + 600 for t in tasks)
        assert db.query(Document).one().status == 'ready'
        assert db.query(Revision).one().body == 'Stored body'
    # Simulate the cooldown elapsing, including loading it in a new DB session.
    with factory.begin() as db:
        for s in db.query(Source):
            s.checkpoint = {**s.checkpoint, 'cooldown_until': 0}
        db.query(Task).order_by(Task.id).first().available = 0
    fetcher.failing = False
    assert process_one(factory, settings, fetcher=fetcher)
    with factory() as db:
        source = db.get(Source, 'nhc-policy')
        assert source.last_success >= before and not source.last_error
        assert cooldown_until(source) == 0
        assert db.query(Snapshot).one().method == 'firefox'
        assert db.query(Document).one().status == 'ready'


def test_new_poll_can_refetch_existing_detail(factory, tmp_path):
    with factory.begin() as db:
        s = db.get(Source, 'nhc-policy'); s.enabled = True
        for bucket in (100, 101):
            enqueue(db, 'list', f'poll-{bucket}', {'source_id': s.id, 'url': s.url, 'bucket': bucket})
    class Fetcher:
        def get(self, url, hosts, **kwargs):
            return b'<ul class="zxxx_list"><li>2026-11-17 <a href="/same.shtml">Same official policy title</a></li></ul>', 'text/html', url
    settings = Settings(object_root=tmp_path / 'objects')
    for _ in range(2):
        process_one(factory, settings, fetcher=Fetcher())
    with factory() as db:
        assert db.query(Task).filter_by(kind='detail').count() == 2


def test_source_failure_does_not_hide_api_history(factory, monkeypatch):
    from fastapi.testclient import TestClient
    from policy_v2 import app as api
    monkeypatch.setattr(api, 'SessionLocal', factory)
    with factory.begin() as db:
        s = db.get(Source, 'hn-policy'); s.enabled = True; s.last_success = 1000
        s.last_error = 'FetchError:ConnectError'; s.checkpoint = {'cooldown_until': time.time() + 600}
        d = Document(source_id=s.id, url='https://wjw.hunan.gov.cn/history.html', region='HN', status='ready')
        db.add(d); db.flush()
        r = Revision(document_id=d.id, number=1, fingerprint='api-history', title='Policy history', body='Original body', kind='policy')
        db.add(r); db.flush(); d.current_revision = r.id; doc_id = d.id
    with TestClient(api.app) as client:
        body = client.get('/api/v2/policies', params={'region':'HN', 'include_national':False}).json()
        assert body['total'] == 1
        assert body['freshness'] == {'last_success':1000, 'unavailable_sources':1}
        assert client.get(f'/api/v2/policies/{doc_id}').json()['body'] == 'Original body'
        rows = client.get('/api/v2/coverage').json()
        assert next(r for r in rows if r['id'] == 'hn-policy')['status'] == 'cooling_down'


def test_retry_after_and_worker_wide_pacing(monkeypatch):
    import policy_v2.network as network
    assert retry_after_seconds('120') == 120
    assert retry_after_seconds(formatdate(1120, usegmt=True), now=1000) == 120
    assert retry_after_seconds('invalid') is None
    clock = [100.0]
    sleeps = []
    monkeypatch.setattr(network.time, 'monotonic', lambda: clock[0])
    def sleep(delay):
        sleeps.append(delay); clock[0] += delay
    monkeypatch.setattr(network.time, 'sleep', sleep)
    fetcher = SafeFetcher(Settings(domain_delay_seconds=2))
    fetcher._pace('www.nhc.gov.cn')
    clock[0] += 0.5
    fetcher._pace('www.nhc.gov.cn')
    fetcher._pace('wjw.hunan.gov.cn')
    assert sleeps == [1.5]


def test_hunan_tls_keeps_verification_and_is_host_scoped(monkeypatch):
    import ssl
    import policy_v2.network as network
    contexts = []
    class Client:
        def __init__(self, **kwargs): contexts.append(kwargs['verify'])
        def close(self): pass
    monkeypatch.setattr(network.httpx, 'Client', Client)
    with SafeFetcher(Settings()) as fetcher:
        hn = fetcher._http_client('wjw.hunan.gov.cn')
        assert hn is fetcher._http_client('wjw.hunan.gov.cn')
        assert hn is not fetcher._http_client('wjw.jiangsu.gov.cn')
    assert len(contexts) == 2
    assert all(c.verify_mode == ssl.CERT_REQUIRED and c.check_hostname for c in contexts)
