import json
from types import SimpleNamespace
import pytest
import httpx
from policy_v2.network import SafeFetcher,FetchError
from policy_v2.settings import Settings
from policy_v2.adapters import read_list
from policy_v2.parsing import ParseError, parse_detail


def test_public_http_exception_is_per_source_and_does_not_leak(monkeypatch):
    import policy_v2.network as network
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',80))])
    fetcher=SafeFetcher(Settings())
    monkeypatch.setattr(fetcher,'_get',lambda url,hosts,**kwargs:(fetcher.validate(url,hosts),'text/plain',url))
    with pytest.raises(FetchError):fetcher.get('http://official.gov.cn/a',['official.gov.cn'])
    assert fetcher.get('http://official.gov.cn/a',['official.gov.cn'],config={'public_http_hosts':['official.gov.cn']})[0]=='official.gov.cn'
    with pytest.raises(FetchError):fetcher.get('http://official.gov.cn/a',['official.gov.cn'])
    with pytest.raises(FetchError):fetcher.get('http://other.gov.cn/a',['official.gov.cn','other.gov.cn'],config={'public_http_hosts':['official.gov.cn']})
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('127.0.0.1',80))])
    with pytest.raises(FetchError,match='non_public_address'):
        fetcher.get('http://official.gov.cn/a',['official.gov.cn'],config={'public_http_hosts':['official.gov.cn']})


def test_public_http_exception_does_not_spread_to_redirect_hosts_or_tls_failures(monkeypatch):
    import policy_v2.network as network
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *a,**k:[(2,1,6,'',('8.8.8.8',80))])
    requested=[]
    def respond(request):
        requested.append(str(request.url))
        if request.url.scheme=='https':raise httpx.ConnectError('certificate verify failed',request=request)
        return httpx.Response(302,headers={'location':'http://cdn.gov.cn/file.pdf'})
    with httpx.Client(transport=httpx.MockTransport(respond)) as client, SafeFetcher(Settings(domain_delay_seconds=0)) as fetcher:
        monkeypatch.setattr(fetcher,'_http_client',lambda *a:client)
        config={'public_http_hosts':['official.gov.cn']}
        with pytest.raises(FetchError,match='url_not_allowed'):
            fetcher.get('http://official.gov.cn/a',['official.gov.cn','cdn.gov.cn'],config=config)
        with pytest.raises(FetchError,match='ConnectError'):
            fetcher.get('https://official.gov.cn/a',['official.gov.cn'],config=config)
    assert requested==['http://official.gov.cn/a','https://official.gov.cn/a']


def test_government_json_feed_counts_raw_records_and_checks_page():
    config={'adapter':'government-json','hosts':['official.gov.cn'],'list_hosts':['official.gov.cn'],'public_http_hosts':['official.gov.cn']}
    data=json.dumps({'data':{'page':1,'rows':2,'total':3,'results':[
        {'title':'政策文件通知测试','url':'/a.shtml','publishedTimeStr':'2026-11-01 10:00'},
        {'title':'外站文件通知测试','url':'https://outside.gov.cn/b.shtml','publishedTimeStr':'2026-11-01'}]}}).encode()
    listing=read_list(data,'http://official.gov.cn/common/search/id?page=1',config)
    assert len(listing.items)==1 and listing.audit['filtered_external']==1
    assert listing.next_url=='http://official.gov.cn/common/search/id?page=2'
    with pytest.raises(ParseError,match='json_page_mismatch'):
        read_list(data,'http://official.gov.cn/common/search/id?page=2',config)


@pytest.mark.parametrize('changes,error',[
    ({'results':[]},'json_feed_incomplete'),
    ({'total':3,'rows':2},'json_feed_incomplete'),
    ({'total':0},'json_feed_count_mismatch'),
    ({'page':0},'json_feed_count_mismatch'),
    ({'channelId':'wrong'},'json_channel_mismatch'),
    ({'results':[{'title':'通知','url':'/a','publishedTimeStr':'invalid'}]},'json_record_malformed'),
])
def test_government_feed_refuses_truncated_or_wrong_channel_results(changes,error):
    payload={'page':1,'rows':1,'total':1,'channelId':'expected',
             'results':[{'title':'测试政策文件','url':'/a','publishedTimeStr':'2026-11-01'}]}
    payload.update(changes)
    config={'adapter':'government-json','hosts':['official.gov.cn'],'feed_channel_id':'expected'}
    with pytest.raises(ParseError,match=error):
        read_list(json.dumps({'data':payload}).encode(),'https://official.gov.cn/feed?page='+str(payload['page']),config)


def test_public_http_attachments_keep_real_images_and_skip_file_icons():
    html='''<div id="body"><p>关于卫生健康政策文件的通知，原文内容公开，附件保留以便查验。</p>
        <img src="images/pdf.gif"><a href="file.pdf">文件附件</a>
        <img src="interpretation.png"><a href="http://elsewhere.gov.cn/a.pdf">外站附件</a></div>'''.encode()
    config={'body_selectors':['#body'],'hosts':['official.gov.cn'],'public_http_hosts':['official.gov.cn']}
    source=SimpleNamespace(config=config,kind='policy')
    parsed=parse_detail(html,'http://official.gov.cn/a/',{'title':'通知','published':'2026-11-01'},source)
    assert [(a['url'],a['status']) for a in parsed['attachments']]==[
        ('http://official.gov.cn/a/file.pdf','pending'),
        ('http://elsewhere.gov.cn/a.pdf','external_reference'),
        ('http://official.gov.cn/a/interpretation.png','pending')]
    config.pop('public_http_hosts')
    assert all(a['status']=='external_reference' for a in parse_detail(html,'http://official.gov.cn/a/',{},source)['attachments'])
