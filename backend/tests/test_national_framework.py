from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
import pytest
from policy_v2.db import Base, database
from policy_v2.domains import acquire, release, DomainBusy
from policy_v2.models import DomainState, Source
from policy_v2.settings import REGIONS, Settings
from policy_v2.sources import inventory, seed, source_definitions
from policy_v2.adapters import read_list
from policy_v2.source_health import record_failure
from policy_v2.network import FetchError


@pytest.fixture
def factory(tmp_path):
    engine,factory=database('sqlite:///'+str(tmp_path/'national.db'))
    Base.metadata.create_all(engine)
    yield factory
    engine.dispose()


def test_inventory_has_all_mainland_provinces_and_sources_start_paused(factory):
    provinces=inventory()
    assert len(provinces)==31 and len({p['region'] for p in provinces})==31
    assert set(REGIONS)=={'CN',*(p['region'] for p in provinces)}
    seed(factory)
    with factory() as db:
        assert all(not s.enabled for s in db.query(Source))
        assert db.query(Source).count()==sum(bool(s.get('config')) for s in source_definitions())


def test_domain_contention_different_hosts_spacing_and_restart(factory):
    one=acquire(factory,'one.gov.cn',seconds=30,now=100)
    two=acquire(factory,'two.gov.cn',seconds=30,now=100)
    with pytest.raises(DomainBusy) as error:acquire(factory,'one.gov.cn',now=101)
    assert error.value.until==130
    assert release(factory,'one.gov.cn',one,2,now=103)
    with pytest.raises(DomainBusy):acquire(factory,'one.gov.cn',now=104)
    new=acquire(factory,'one.gov.cn',seconds=30,now=105)
    # A crashed worker is reclaimable, and its old owner cannot release the new lease.
    newer=acquire(factory,'one.gov.cn',now=136)
    assert newer!=new and not release(factory,'one.gov.cn',new,2,now=137)
    assert release(factory,'two.gov.cn',two,2,now=138)


@pytest.mark.parametrize('precreated',[True,False])
def test_two_workers_cannot_own_same_domain(factory,precreated):
    # Precreate row to test the cross-connection compare-and-swap under contention.
    if precreated:
        with factory.begin() as db:db.add(DomainState(host='same.gov.cn'))
    start=Barrier(2)
    def attempt(_):
        start.wait()
        try:return acquire(factory,'same.gov.cn',now=100)
        except DomainBusy:return None
    with ThreadPoolExecutor(2) as pool:owners=list(pool.map(attempt,range(2)))
    assert sum(o is not None for o in owners)==1


def test_retry_after_survives_release_and_applies_to_sibling_columns(factory):
    seed(factory)
    owner=acquire(factory,'wjw.jiangsu.gov.cn',now=100)
    until=record_failure(factory,'js-policy',FetchError('http_429',retry_after=900),Settings(),now=101)
    assert release(factory,'wjw.jiangsu.gov.cn',owner,2,now=102)
    with pytest.raises(DomainBusy) as error:acquire(factory,'wjw.jiangsu.gov.cn',now=103)
    assert error.value.until==until==1001
    with factory() as db:assert db.get(Source,'js-interpretation').checkpoint['cooldown_until']==1001


def test_zero_based_pagination_and_content_filter_keep_audit():
    data='''<ul><li>2026-01-02<a href="/a.html">政策文件发布通知</a></li>
    <li>2026-01-02<a href="/b.html">政策文件图解说明</a></li>
    <li>2026-01-02<a href="https://other.gov.cn/c.html">其他地区政策文件</a></li></ul>
    <script>createPageHTML(3,0,'index','html')</script>'''.encode()
    result=read_list(data,'https://one.gov.cn/column/',{
        'list_selector':'li','hosts':['one.gov.cn'],'include_title_pattern':'图解',
        'pagination':{'pattern':r'createPageHTML\((?P<total>\d+),(?P<current>\d+)','template':'index_{page}.html'}})
    assert [i['url'] for i in result.items]==['https://one.gov.cn/b.html']
    assert result.next_url=='https://one.gov.cn/column/index_1.html'
    assert result.audit['filtered_external']==1 and result.audit['filtered_content_type']==1
    last=read_list(data.replace(b'(3,0',b'(3,2'),'https://one.gov.cn/column/index_2.html',{
        'list_selector':'li','hosts':['one.gov.cn'],
        'pagination':{'pattern':r'createPageHTML\((?P<total>\d+),(?P<current>\d+)','template':'index_{page}.html'}})
    assert last.next_url is None


def test_partial_list_date_is_not_invented():
    data='<ul><li><a href="/20261105/index.shtml">文件政策解读测试</a><span>11-04</span></li></ul>'.encode()
    result=read_list(data,'https://one.gov.cn/list.shtml',{'list_selector':'li','hosts':['one.gov.cn'],'date_from_detail':True})
    assert result.items[0]['published'] is None


def test_task_heartbeat_and_stale_owner_cannot_write(factory):
    import time
    from policy_v2.db import transaction
    from policy_v2.models import Task
    from policy_v2.queue import enqueue, claim, keep_lease, assert_ownership, TaskLeaseLost
    with transaction(factory) as db:enqueue(db,'list','lease-test',{})
    task=claim(factory,1)
    with keep_lease(factory,task,1):
        time.sleep(1.15)
        assert claim(factory,1) is None
        with transaction(factory) as db:db.get(Task,task['id']).owner='replacement'
        with factory() as db:
            with pytest.raises(TaskLeaseLost):assert_ownership(db,task)


def test_fetch_reserves_redirect_hosts_and_defers_without_request(factory,monkeypatch):
    from policy_v2.network import SafeFetcher
    fetcher=SafeFetcher(Settings(domain_delay_seconds=0),factory)
    monkeypatch.setattr(fetcher,'validate',lambda url,hosts:'one.gov.cn')
    seen=[]
    def request(*args,**kwargs):
        for host in ['one.gov.cn','cdn.gov.cn']:
            with pytest.raises(DomainBusy):acquire(factory,host)
        seen.append(True);return b'data','text/plain','https://one.gov.cn/'
    monkeypatch.setattr(fetcher,'_get',request)
    fetcher.get('https://one.gov.cn/',['one.gov.cn','cdn.gov.cn'])
    owner=acquire(factory,'cdn.gov.cn')
    with pytest.raises(DomainBusy):fetcher.get('https://one.gov.cn/',['one.gov.cn','cdn.gov.cn'])
    assert len(seen)==1
    release(factory,'cdn.gov.cn',owner,0)


def test_media_and_unapproved_attachments_keep_reference_without_download():
    from types import SimpleNamespace
    from policy_v2.parsing import parse_detail
    data=b'''<article><iframe durl="/video.mp4" src="/player"></iframe>
    <a href="https://outside.gov.cn/file.pdf">PDF</a><img src="/fileTypeImages/icon_pdf.gif"></article>'''
    source=SimpleNamespace(config={'body_selectors':['article'],'hosts':['one.gov.cn']},kind='interpretation')
    parsed=parse_detail(data,'https://one.gov.cn/a.html',{'title':'Policy','published':'2026-01-01'},source)
    assert [a['status'] for a in parsed['attachments']]==['needs_transcription','external_reference']
    assert parsed['authority']==''


def test_liaoning_terminal_placeholder_is_not_requested():
    result=read_list('<li>2026-01-01<a href="a.html">文件公开管理办法</a></li><a title="下一页" tagname="[NEXTPAGE]">下一页</a>'.encode(),
        'https://one.gov.cn/list.html',{'hosts':['one.gov.cn'],'list_selector':'li','next_selector':'a[title="下一页"]','next_attribute':'tagname'})
    assert result.next_url is None


def test_multithreaded_worker_schedules_enabled_sources_and_persists_documents(factory,tmp_path,monkeypatch):
    from threading import Event
    from policy_v2 import worker
    from policy_v2.models import Document,Task
    from policy_v2.db import transaction
    from policy_v2.queue import enqueue
    stop=Event();count=0
    with transaction(factory) as db:
        for i in range(2):
            id='test'+str(i);url=f'https://host{i}.gov.cn/list.html'
            db.add(Source(id=id,name=id,region='CN',kind='policy',url=url,enabled=True,
                config={'hosts':[f'host{i}.gov.cn'],'list_selector':'li','body_selectors':['article']}))
    class Fetcher:
        def __init__(self,*args):pass
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,hosts,**kwargs):
            if kwargs['page_kind']=='list':
                return '<li>2026-11-01<a href="/a.html">政策文件管理办法测试</a></li>'.encode(),'text/html',url
            return '<article>这里是测试用的完整政策正文，包含足够的文字以验证原文持久化和多线程任务消费，不访问任何外部站点。</article>'.encode(),'text/html',url
    monkeypatch.setattr(worker,'SafeFetcher',Fetcher)
    import threading,time
    thread=threading.Thread(target=worker.run_workers,args=(factory,Settings(object_root=tmp_path/'objects'),2,stop))
    thread.start()
    try:
        deadline=time.monotonic()+8
        while time.monotonic()<deadline:
            with factory() as db:
                if db.query(Document).count()==2:break
            stop.wait(.05)
        with factory() as db:assert db.query(Document).count()==2
    finally:stop.set();thread.join(timeout=5)
    assert not thread.is_alive()


def test_wrong_download_mime_and_query_filename_are_handled():
    from io import BytesIO
    from docx import Document
    from policy_v2.extraction import extract
    from policy_v2.network import SafeFetcher
    out=BytesIO();doc=Document();doc.add_paragraph('Policy attachment text');doc.save(out)
    data=out.getvalue()
    assert SafeFetcher._check_attachment(data,'text/html')=='application/zip'
    blocks,status=extract(data,'https://one.gov.cn/downfile.jsp?filename=policy.docx')
    assert status=='ready' and blocks[0]['text']=='Policy attachment text'
    with pytest.raises(FetchError,match='attachment_returned_html'):
        SafeFetcher._check_attachment(b'<html>blocked</html>','application/octet-stream')


def test_fetch_failure_persists_cooldown_before_another_worker_can_enter(factory,monkeypatch):
    import time
    from policy_v2.network import SafeFetcher
    fetcher=SafeFetcher(Settings(domain_delay_seconds=0),factory)
    monkeypatch.setattr(fetcher,'validate',lambda url,hosts:'one.gov.cn')
    def fail(*args,**kwargs):raise FetchError('http_429',retry_after=900)
    monkeypatch.setattr(fetcher,'_get',fail)
    start=time.time()
    with pytest.raises(FetchError):fetcher.get('https://one.gov.cn/',['one.gov.cn'])
    with pytest.raises(DomainBusy) as exc:acquire(factory,'one.gov.cn')
    assert exc.value.until>=start+900
