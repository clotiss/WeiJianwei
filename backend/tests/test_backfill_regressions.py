import gzip
from pathlib import Path
from types import SimpleNamespace

from policy_v2.parsing import parse_detail
from policy_v2.sources import source_definitions
from policy_v2.adapters import read_list


def test_beijing_video_only_interpretation_retains_original_media_link():
    data = gzip.decompress((Path(__file__).parent / 'fixtures/national/bj-interpretation-video-only.html.gz').read_bytes())
    source = SimpleNamespace(**next(s for s in source_definitions() if s['id'] == 'bj-interpretation'))
    parsed = parse_detail(data, 'https://wjw.beijing.gov.cn/zwgk_20040/zcjd2024/202405/t20240525_3694186.html',
        {'title': '视频：《优化生育政策 促进人口长期均衡发展》', 'published': '2023-03-22'}, source)
    assert parsed['kind'] == 'interpretation'
    assert parsed['body'] == ''
    assert len(parsed['attachments']) == 1
    assert parsed['attachments'][0]['url'].endswith('.mp4')
    assert parsed['attachments'][0]['status'] == 'needs_transcription'


def test_guizhou_last_page_after_official_jump_has_no_more_pages():
    data = gzip.decompress((Path(__file__).parent / 'fixtures/national/gz-policy-last-page-jump.html.gz').read_bytes())
    source = next(s for s in source_definitions() if s['id'] == 'gz-policy')
    listing = read_list(data, source['url'] + '#collector-page=21', source['config'])
    assert len(listing.items) == 4 and listing.next_url is None
