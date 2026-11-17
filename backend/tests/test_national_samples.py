"""Captured official pages guard site-specific titles, dates, pagination and bodies."""
import gzip
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from policy_v2.adapters import read_list
from policy_v2.parsing import parse_detail
from policy_v2.sources import source_definitions

ROOT=Path(__file__).resolve().parents[2]
SAMPLES=json.loads((ROOT/'backend/tests/fixtures/national/manifest.json').read_text())
SOURCES={s['id']:s for s in source_definitions()}


@pytest.mark.parametrize('sample',SAMPLES,ids=[Path(s['fixture']).name for s in SAMPLES])
def test_captured_official_page(sample):
    data=gzip.decompress((ROOT/sample['fixture']).read_bytes())
    assert hashlib.sha256(data).hexdigest()==sample['sha256']
    source=SOURCES[sample['source']]
    if sample['kind']=='list':
        actual=read_list(data,sample['url'],source['config'])
        assert {'items':actual.items,'next_url':actual.next_url,'audit':actual.audit}==sample['expected']
    else:
        actual=parse_detail(data,sample['url'],sample['item'],SimpleNamespace(**source))
        expected=sample['expected']
        assert {k:actual[k] for k in ('title','published','authority','kind','attachments')}=={k:expected[k] for k in ('title','published','authority','kind','attachments')}
        assert hashlib.sha256(actual['body'].encode()).hexdigest()==expected['body_sha256']
        assert len(actual['body'])==expected['body_chars']


def test_each_enabled_adapter_has_both_list_and_detail_regressions():
    configured={s['id'] for s in SOURCES.values() if s.get('config')}
    assert configured=={s['source'] for s in SAMPLES if s['kind']=='list'}=={s['source'] for s in SAMPLES if s['kind']=='detail'}
