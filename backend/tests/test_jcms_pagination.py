from pathlib import Path

import pytest

from policy_v2.parsing import parse_list, jcms_group, ParseError
from policy_v2.sources import SPECS, source_config


@pytest.mark.parametrize('sid,expected', [('js-policy', 45), ('js-interpretation', 1)])
def test_jcms_embedded_first_group_does_not_end_history(sid, expected):
    spec = next(s for s in SPECS if s[0] == sid)
    data = (Path(__file__).parent / 'fixtures' / f'{sid}-jcms.html').read_bytes()
    items, next_url = parse_list(data, spec[4], source_config(spec))
    assert len(items) == expected
    assert next_url, 'Official totalRecord exceeds the first 45 embedded rows; history must continue'


@pytest.mark.parametrize('sid,total,accepted', [('js-policy',47,47), ('js-interpretation',202,26)])
def test_full_xml_reaches_official_total_and_ignores_stale_nextgroup(sid,total,accepted):
    spec = next(s for s in SPECS if s[0] == sid)
    config = source_config(spec)
    data = (Path(__file__).parent / 'fixtures' / f'{sid}-full.xml').read_bytes()
    items,next_url = parse_list(data,spec[4],config)
    assert len(items) == accepted and next_url is None
    audit = jcms_group(data,spec[4],config)[2]
    assert audit['returned_records'] == audit['total_records'] == total
    assert audit['complete_listing'] is True
    if sid == 'js-interpretation':
        assert audit['link_origins']['mp.weixin.qq.com'] == 83
        assert audit['link_origins']['wjw.jiangsu.gov.cn'] == 33
        assert audit['filtered_external'] == 169
        assert audit['filtered_content_type'] == 7
        assert not any('这些要知道' in item['title'] for item in items)


def test_filtered_external_group_still_continues_and_malformed_response_fails():
    spec = next(s for s in SPECS if s[0] == 'js-interpretation')
    config = source_config(spec)
    data = b'''<datastore><totalrecord>2</totalrecord><nextgroup><![CDATA[<a href="/module/web/jpage/dataproxy.jsp?page=2&columnid=7292"></a>]]></nextgroup><recordset>
    <record><![CDATA[<li>2026-11-17 <a href="https://mp.weixin.qq.com/s/example">External official article title</a></li>]]></record>
    </recordset></datastore>'''
    items,next_url = parse_list(data,spec[4],config)
    assert items == [] and next_url.endswith('page=2&columnid=7292')
    with pytest.raises(ParseError,match='jcms_datastore_missing'):
        parse_list(b'<html>upstream failure</html>',spec[4],config)
    with pytest.raises(ParseError,match='jcms_next_group_not_allowed'):
        parse_list(data.replace(b'/module/web/',b'https://unregistered.example/module/web/'),spec[4],config)
    with pytest.raises(ParseError,match='jcms_record_malformed'):
        parse_list(data.replace(b'2026-11-17',b'no date'),spec[4],config)


def test_worker_fetches_followup_once_and_deduplicates_repeated_items(tmp_path, monkeypatch):
    from policy_v2.db import Base,database
    from policy_v2.models import Source,Task
    from policy_v2.sources import seed
    from policy_v2.pipeline import discover,process_one
    from policy_v2.settings import Settings
    engine,factory=database(f"sqlite:///{tmp_path / 'jcms.db'}")
    Base.metadata.create_all(engine);seed(factory)
    with factory.begin() as db:db.get(Source,'js-policy').enabled=True
    class Fetcher:
        calls=[]
        def get(self,url,hosts,**kwargs):
            self.calls.append(url)
            assert kwargs['page_kind']=='list'
            filename='js-policy-full.xml' if 'dataproxy.jsp' in url else 'js-policy-jcms.html'
            return (Path(__file__).parent/'fixtures'/filename).read_bytes(),'text/xml',url
    fetcher=Fetcher();settings=Settings(object_root=tmp_path/'objects')
    try:
        discover(factory,'js-policy')
        assert process_one(factory,settings,fetcher=fetcher)
        # Advance the list follow-up before details, then verify its queue effects.
        with factory.begin() as db:
            task=db.query(Task).filter_by(kind='list',state='queued').one();task.priority=0
        assert process_one(factory,settings,fetcher=fetcher)
        with factory() as db:
            assert len(fetcher.calls)==2
            assert db.query(Task).filter_by(kind='list',state='succeeded').count()==2
            assert db.query(Task).filter_by(kind='list',state='queued').count()==0
            assert db.query(Task).filter_by(kind='detail').count()==47
            audit=db.get(Source,'js-policy').checkpoint['last_listing']
            assert audit['complete_listing'] and audit['returned_records']==47
        from fastapi.testclient import TestClient
        from policy_v2 import app as api
        monkeypatch.setattr(api,'SessionLocal',factory)
        monkeypatch.setattr(api.settings,'admin_token','test-audit-token')
        with TestClient(api.app) as client:
            rows=client.get('/api/v2/admin/sources',headers={'Authorization':'Bearer test-audit-token'}).json()
            source=next(row for row in rows if row['id']=='js-policy')
            assert source['listing_audit']['total_records']==47
    finally:engine.dispose()
