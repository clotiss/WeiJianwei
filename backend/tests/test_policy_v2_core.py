from pathlib import Path

import pytest

from policy_v2.db import Base, database
from policy_v2.models import Source
from policy_v2.parsing import ParseError, canonical, parse_detail, parse_list, page_url
from policy_v2.queue import claim, enqueue, finish
from policy_v2.settings import Settings
from policy_v2.storage import LocalStore
from policy_v2.network import FetchError, SafeFetcher
from policy_v2.migrate import migrate_documents
from policy_v2.sources import seed
from policy_v2.pipeline import discover
from policy_v2.pipeline import process_one


@pytest.fixture
def factory(tmp_path):
    engine, factory = database(f"sqlite:///{tmp_path / 'test.db'}")
    Base.metadata.create_all(engine)
    yield factory
    engine.dispose()


def test_storage_is_content_addressed_and_rejects_traversal(tmp_path):
    store = LocalStore(tmp_path)
    first = store.put(b"official source", "text/html")
    second = store.put(b"official source", "application/octet-stream")
    assert first["sha"] == second["sha"]
    assert store.read(first["key"]) == b"official source"
    with pytest.raises(ValueError, match="invalid_object_key"):
        store.read("../../outside")


def test_parse_list_keeps_only_dated_allowlisted_documents():
    html = b'''<ul class="items"><li>2026-11-01 <a href="/policy/one.shtml">A sufficiently long policy title</a></li>
    <li>2026-11-02 <a href="https://evil.example/policy.shtml">External link title</a></li>
    <li><a href="/policy/two.shtml">No date item title</a></li></ul>'''
    items, next_url = parse_list(html, "https://official.example/list.html", {
        "list_selector": ".items li", "hosts": ["official.example"]
    })
    assert len(items) == 1
    assert items[0]["published"] == "2026-11-01"
    assert items[0]["url"] == "https://official.example/policy/one.shtml"
    assert next_url is None


def test_list_source_host_filter_rejects_cross_domain_reposts():
    html = b'''<ul class="items">
    <li>2026-11-01 <a href="https://province.example/policy.shtml">Province policy title</a></li>
    <li>2026-11-02 <a href="https://national.example/policy.shtml">National repost title</a></li></ul>'''
    items, _ = parse_list(html, "https://province.example/list.html", {
        "list_selector": ".items li",
        "hosts": ["province.example", "national.example"],
        "list_hosts": ["province.example"],
    })
    assert [item["title"] for item in items] == ["Province policy title"]


def test_empty_list_is_an_error_not_a_false_success():
    with pytest.raises(ParseError, match="list_empty"):
        parse_list(b"<html><body>blocked</body></html>", "https://official.example/list.html", {
            "list_selector": ".items li", "hosts": ["official.example"]
        })


def test_saved_guangdong_official_pages_match_registered_selectors():
    evidence = Path(__file__).resolve().parent / "fixtures"
    for filename, url, host in [
        ("gd-policy.html", "https://wsjkw.gd.gov.cn/hdjl/hdjl_zcwj/index.html", "wsjkw.gd.gov.cn"),
        ("gd-interpretation.html", "https://wsjkw.gd.gov.cn/hdjl_zcjd/index.html", "wsjkw.gd.gov.cn"),
    ]:
        data = (evidence / filename).read_bytes()
        items, next_url = parse_list(data, url, {"list_selector": ".section.list li", "hosts": [host, "www.nhc.gov.cn", "www.gd.gov.cn"]})
        assert len(items) >= 10
        assert next_url and next_url.startswith("https://wsjkw.gd.gov.cn/")


def test_official_province_body_containers_are_supported():
    source = Source(id="test", name="Test Health Commission", region="GD", kind="policy",
                    url="https://official.example/list.html", config={"body_selectors": [
                        ".content-content", ".main-fl.bt-left"
                    ]})
    pages = [
        (b'<div class="content-content"><p>Guangdong official policy text with enough characters to pass body validation.</p></div>',
         "Guangdong official policy text with enough characters to pass body validation."),
        (b'<div class="main-fl bt-left"><p>Jiangsu official policy text with enough characters to pass body validation.</p></div>',
         "Jiangsu official policy text with enough characters to pass body validation."),
    ]
    for page, body in pages:
        result = parse_detail(page, "https://official.example/policy/a.shtml", {"title": "Official policy title"}, source)
        assert result["body"] == body


def test_jiangsu_interpretation_source_rejects_nhc_reposts():
    from policy_v2.sources import SPECS
    source = next(spec for spec in SPECS if spec[0] == "js-interpretation")
    assert source[6] == "li"
    assert source[7] == ["wjw.jiangsu.gov.cn"]


def test_worker_processes_registered_list_and_detail_into_versioned_document(tmp_path, factory, monkeypatch):
    import policy_v2.pipeline as pipeline
    from policy_v2.models import Document, RawObject, Revision, Snapshot
    seed(factory)
    with factory() as db:
        source = db.get(Source, "gd-policy")
        source.enabled = True
        source.config = {**source.config, "hosts": ["wsjkw.gd.gov.cn"], "list_selector": ".items li",
                         "body_selectors": ["#article"]}
        db.commit()

    listing = b'<ul class="items"><li>2026-10-10 <a href="https://wsjkw.gd.gov.cn/policy/a.shtml">Official policy announcement title</a></li></ul>'
    detail = '''<html><head><meta name="PubDate" content="2026-10-10"></head><body><article id="article">
    <p>This is an official policy text that is long enough to be retained as a usable document body.</p></article></body></html>'''.encode()
    class FakeFetcher:
        def __init__(self, settings): pass
        def get(self, url, hosts): return (listing if url.endswith('index.html') else detail, 'text/html', url)
    monkeypatch.setattr(pipeline, "SafeFetcher", FakeFetcher)
    settings = Settings(object_root=tmp_path / "objects", task_lease_seconds=30, task_max_attempts=2)
    assert discover(factory, "gd-policy") == 1
    assert process_one(factory, settings) is True
    assert process_one(factory, settings) is True
    with factory() as db:
        doc = db.query(Document).one()
        revision = db.query(Revision).one()
        assert doc.status == "ready" and doc.current_revision == revision.id
        assert revision.title == "Official policy announcement title"
        assert "official policy text" in revision.body
        assert revision.snapshot_id is not None
        assert db.query(Snapshot).count() == 2
        assert db.query(RawObject).count() == 2


def test_detail_extracts_body_and_attachment_and_excludes_unrequested_types():
    source = Source(id="test", name="Test Health Commission", region="CN", kind="policy",
                    url="https://official.example/list.html", config={"body_selectors": ["#article"]})
    page = '''<html><head><meta name="PubDate" content="2026-10-10"></head><body><article id="article">
      <h1>Official document title</h1><p>This is the official policy body with enough text for a meaningful record.</p>
      <a href="/files/notice.pdf">PDF</a><a href="/policy/interpretation.shtml">政策解读</a>
      </article></body></html>'''.encode()
    result = parse_detail(page, "https://official.example/policy/main.shtml", {"title": "Official document title", "published": "2026-10-09"}, source)
    assert result["published"] == "2026-10-10"
    assert result["attachments"][0]["url"] == "https://official.example/files/notice.pdf"
    assert result["links"][0]["url"].endswith("interpretation.shtml")
    assert result["kind"] == "policy"


def test_pagination_rules_are_explicit():
    assert page_url("https://official.example/list.shtml", 2, "nhc").endswith("list_2.shtml")
    assert page_url("https://official.example/index.html", 2, "gd").endswith("index_1.html")
    assert page_url("https://official.example/index.html", 2, "jcms") is None
    assert canonical("HTTPS://OFFICIAL.EXAMPLE/a.shtml?x=1#part") == "https://official.example/a.shtml?x=1"


def test_task_claim_is_idempotent_and_finishes(factory):
    with factory() as db:
        first = enqueue(db, "fetch", "same-key", {"url": "https://official.example/a"})
        second = enqueue(db, "fetch", "same-key", {"url": "https://official.example/a"})
        assert first.id == second.id
    task = claim(factory)
    assert task and task["attempts"] == 1
    assert finish(factory, task) is True
    assert claim(factory) is None


def test_discovery_starts_paused_and_only_enabled_sources_are_queued(factory):
    seed(factory)
    assert discover(factory, "gd-policy") == 0
    with factory() as db:
        source = db.get(__import__('policy_v2.models', fromlist=['Source']).Source, "gd-policy")
        source.enabled = True
        db.commit()
    assert discover(factory, "gd-policy") == 1
    with factory() as db:
        tasks = db.query(__import__('policy_v2.models', fromlist=['Task']).Task).all()
        assert len(tasks) == 1
        assert tasks[0].payload["url"].endswith("index.html")


def test_seed_refreshes_adapter_config_without_changing_enable_state(factory):
    seed(factory)
    with factory() as db:
        source = db.get(Source, "js-interpretation")
        source.enabled = True
        source.config = {**source.config, "list_hosts": ["wjw.jiangsu.gov.cn", "www.nhc.gov.cn"],
                         "body_selectors": ["#old-selector"]}
        db.commit()
    seed(factory)
    with factory() as db:
        source = db.get(Source, "js-interpretation")
        assert source.enabled is True
        assert source.config["list_hosts"] == ["wjw.jiangsu.gov.cn"]
        assert ".main-fl.bt-left" in source.config["body_selectors"]


def test_fetcher_rejects_non_https_and_unregistered_hosts():
    fetcher = SafeFetcher(Settings())
    with pytest.raises(FetchError, match="url_not_allowed"):
        fetcher.validate("http://official.example/a", ["official.example"])
    with pytest.raises(FetchError, match="url_not_allowed"):
        fetcher.validate("https://other.example/a", ["official.example"])


def test_fetcher_uses_firefox_for_nhc_412(monkeypatch):
    import policy_v2.network as network

    class Response:
        status_code = 412
        headers = {}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def iter_bytes(self): return iter(())

    class Client:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def stream(self, *args, **kwargs): return Response()

    monkeypatch.setattr(network.httpx, "Client", lambda **kwargs: Client())
    fetcher = SafeFetcher(Settings(domain_delay_seconds=0))
    monkeypatch.setattr(fetcher, "validate", lambda url, hosts: "www.nhc.gov.cn")
    monkeypatch.setattr(fetcher, "_get_firefox", lambda url, hosts: (b"rendered", "text/html", url))
    assert fetcher.get("https://www.nhc.gov.cn/policies.shtml", ["www.nhc.gov.cn"]) == (
        b"rendered", "text/html", "https://www.nhc.gov.cn/policies.shtml"
    )


def test_migration_preserves_legacy_id_and_does_not_fabricate_raw_snapshot(tmp_path, factory):
    legacy = tmp_path / "legacy.db"
    import sqlite3
    with sqlite3.connect(legacy) as db:
        db.execute("CREATE TABLE documents (id INTEGER PRIMARY KEY, title TEXT, doc_number TEXT, issuing_authority TEXT, publish_date TEXT, category TEXT, doc_type TEXT, original_url TEXT, content TEXT, summary TEXT, attachments TEXT)")
        db.execute("INSERT INTO documents VALUES (41, 'Policy title', 'NHC-1', 'NHC', '2026-01-02', '基层医疗', '规范性文件', 'https://www.nhc.gov.cn/a.shtml', 'Full legacy body', '[]', '[]')")
        db.commit()
    seed(factory)
    result = migrate_documents(legacy, factory)
    assert result == {"imported": 1, "skipped": 0, "total": 1}
    with factory() as db:
        doc = db.query(__import__('policy_v2.models', fromlist=['Document']).Document).one()
        revision = db.query(__import__('policy_v2.models', fromlist=['Revision']).Revision).one()
        assert doc.legacy_id == 41 and doc.status == "ready"
        assert revision.body == "Full legacy body"
        assert revision.snapshot_id is None
