from types import SimpleNamespace
import pytest

from fastapi.testclient import TestClient
from policy_v2.db import Base, database
from policy_v2.ingestion import persist_detail
from policy_v2.models import Revision, Source
from policy_v2.parsing import parse_detail, paragraph_text, soup
from policy_v2.settings import Settings
from policy_v2.storage import LocalStore

HTML = '''<article><p>国家卫生健康委<span>办公厅</span></p>
<p><span>2026</span>年<span>10</span>月<span>20</span>日</p>
<p>现印发给你们，请遵照执行<span>。</span></p>
<p><b>第一条</b> 为加强我国罕见病管理。</p></article>'''
EXPECTED = '国家卫生健康委办公厅\n2026年10月20日\n现印发给你们,请遵照执行。\n第一条 为加强我国罕见病管理。'
CONFIG = {'body_selectors': ['article'], 'hosts': ['official.example']}


def test_inline_fonts_do_not_split_dates_punctuation_or_paragraphs():
    parsed = parse_detail(HTML, 'https://official.example/a', {'title': '政策通知'},
                          SimpleNamespace(kind='policy', config=CONFIG))
    assert parsed.get('display_body', parsed['body']) == EXPECTED


@pytest.mark.parametrize('html,expected', [
    ('<article><h2>第一章</h2><p>正文<b>重点</b>。</p><p>下一段。</p></article>', '第一章\n正文重点。\n下一段。'),
    ('<article><p>第一行<br>第二行</p><ul><li>条目一</li><li>条目二</li></ul></article>', '第一行\n第二行\n条目一\n条目二'),
    ('<article><table><tr><th>机构</th><th>人数</th></tr><tr><td>甲</td><td>10</td></tr></table></article>', '机构 人数\n甲 10'),
    ('<article><p><b>World</b> Health <span>Organization</span></p></article>', 'World Health Organization'),
])
def test_real_paragraphs_lists_tables_and_english_spacing_remain(html, expected):
    assert paragraph_text(soup(html).article) == expected


def test_existing_revision_gets_readable_body_without_changing_summary_evidence(tmp_path, monkeypatch):
    import policy_v2.app as api
    settings = Settings(database_url='sqlite:///' + str(tmp_path / 'test.db'), object_root=tmp_path / 'objects')
    engine, factory = database(settings.database_url)
    Base.metadata.create_all(engine)
    store = LocalStore(settings.object_root)
    with factory.begin() as db:
        source = Source(id='test', name='官方来源', region='CN', kind='policy',
                        url='https://official.example/list', config=CONFIG)
        db.add(source)
        parsed = parse_detail(HTML, 'https://official.example/a', {'title': '政策通知'}, source)
        document, revision, _ = persist_detail(db, source, parsed, store.put(HTML.encode(), 'text/html'),
                                              'https://official.example/a', method='httpx')
        original = revision.body
        assert '2026\n年\n10\n月\n20\n日' in original
        quote = '2026\n年\n10\n月\n20\n日'
        start = original.index(quote)
        revision.summary_status = 'ready'
        revision.summary = [{'text': '发文日期为2026年10月20日。', 'quote': quote,
                             'source': 'body', 'start': start, 'end': start + len(quote)}]
        did, rid = document.id, revision.id
    monkeypatch.setattr(api, 'SessionLocal', factory)
    monkeypatch.setattr(api, 'settings', settings)
    try:
        with TestClient(api.app) as client:
            result = client.get(f'/api/v2/policies/{did}').json()
        assert result.get('display_body') == EXPECTED
        assert result['body'] == original
        point = result['summary'][0]
        assert result['body'][point['start']:point['end']] == point['quote']
        with factory() as db:
            assert db.get(Revision, rid).body == original
            assert db.get(Revision, rid).summary_status == 'ready'
            assert db.query(Revision).count() == 1
        # A missing snapshot must still leave the saved text readable.
        for path in settings.object_root.rglob('*'):
            if path.is_file(): path.unlink()
        with TestClient(api.app) as client:
            assert client.get(f'/api/v2/policies/{did}').json()['display_body'] == original
    finally:
        engine.dispose()
