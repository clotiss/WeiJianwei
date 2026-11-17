"""Explicit allowlist, per-column adapters. Sources start paused until a trial is reviewed."""
from .models import Source
from .db import transaction
from urllib.parse import urlsplit

COMMON_BODY=['#UCAP-CONTENT','#xw_box','.TRS_Editor','#zoom','.article-content','.article_cont','.content-text','.content-content','.main-fl.bt-left','#content']
SPECS=[
 ('nhc-policy','国家卫生健康委','CN','policy','https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml','nhc','.zxxx_list li',['www.nhc.gov.cn']),
 ('nhc-interpretation','国家卫生健康委','CN','interpretation','https://www.nhc.gov.cn/wjw/zcjd/list.shtml','nhc','.zxxx_list li',['www.nhc.gov.cn']),
 ('js-policy','江苏省卫生健康委员会','JS','policy','https://wjw.jiangsu.gov.cn/col/col81326/index.html','jcms','li',['wjw.jiangsu.gov.cn','www.nhc.gov.cn']),
 ('js-interpretation','江苏省卫生健康委员会','JS','interpretation','https://wjw.jiangsu.gov.cn/col/col7292/index.html','jcms','li',['wjw.jiangsu.gov.cn']),
 ('hn-policy','湖南省卫生健康委员会','HN','policy','https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/gfxwj/index.html','trs','.table_list tr',['wjw.hunan.gov.cn']),
 ('hn-interpretation','湖南省卫生健康委员会','HN','interpretation','https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/zcjd/index.html','trs','.table_list tr',['wjw.hunan.gov.cn']),
 ('gd-policy','广东省卫生健康委员会','GD','policy','https://wsjkw.gd.gov.cn/hdjl/hdjl_zcwj/index.html','gd','.section.list li',['wsjkw.gd.gov.cn','www.nhc.gov.cn','www.gd.gov.cn']),
 ('gd-interpretation','广东省卫生健康委员会','GD','interpretation','https://wsjkw.gd.gov.cn/hdjl_zcjd/index.html','gd','.section.list li',['wsjkw.gd.gov.cn','www.nhc.gov.cn','www.gd.gov.cn']),
]

def source_config(spec):
    id, name, region, kind, url, adapter, selector, hosts = spec
    config = {'adapter': adapter, 'list_selector': selector, 'body_selectors': COMMON_BODY,
              'hosts': hosts, 'list_hosts': [urlsplit(url).hostname], 'max_pages': 3}
    if id.startswith('nhc-'):
        config['pagination'] = 'nhc-static'
    if id.startswith('js-'):
        config['jcms_column_id'] = 81326 if id == 'js-policy' else 7292
    if id == 'js-interpretation':
        config['include_title_pattern'] = '解读|图解|一图读懂|问答|答记者问'
    if id.startswith('hn-'):
        config['pagination'] = 'hunan-trs'
        config['body_selectors'] = ['#j-show-body', *COMMON_BODY]
        config['published_selector'] = '.main_con_ftit'
        config['published_from_list'] = True  # Hunan PubDate is often page-generation time.
    if id == 'hn-interpretation':
        # The official column mixes reports, original policies and interpretations.
        config['include_title_pattern'] = '解读|图解|问答'
    return config

def seed(factory):
    with transaction(factory) as db:
        for id,name,region,kind,url,adapter,selector,hosts in SPECS:
            config=source_config((id,name,region,kind,url,adapter,selector,hosts))
            source=db.get(Source,id)
            if not source:
                db.add(Source(id=id,name=name,region=region,kind=kind,url=url,config=config,enabled=False))
            else:
                source.name=name;source.region=region;source.kind=kind;source.url=url
                source.config={**dict(source.config or {}),**config}
