"""Explicit allowlist, per-column adapters. Sources start paused until a trial is reviewed."""
from .models import Source
from .db import transaction

COMMON_BODY=['#UCAP-CONTENT','#xw_box','.TRS_Editor','#zoom','.article-content','.article_cont','.content-text','#content']
SPECS=[
 ('nhc-policy','国家卫生健康委','CN','policy','https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml','nhc','.zxxx_list li',['www.nhc.gov.cn']),
 ('nhc-interpretation','国家卫生健康委','CN','interpretation','https://www.nhc.gov.cn/wjw/zcjd/list.shtml','nhc','.zxxx_list li',['www.nhc.gov.cn']),
 ('js-policy','江苏省卫生健康委员会','JS','policy','https://wjw.jiangsu.gov.cn/col/col81326/index.html','jcms','li',['wjw.jiangsu.gov.cn','www.nhc.gov.cn']),
 ('js-interpretation','江苏省卫生健康委员会','JS','interpretation','https://wjw.jiangsu.gov.cn/col/col7292/index.html','jcms','li',['wjw.jiangsu.gov.cn','www.nhc.gov.cn']),
 ('hn-policy','湖南省卫生健康委员会','HN','policy','https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/gfxwj/index.html','trs','.list li, .news_list li, .list-unstyled li',['wjw.hunan.gov.cn']),
 ('hn-interpretation','湖南省卫生健康委员会','HN','interpretation','https://wjw.hunan.gov.cn/wjw/xxgk/zcfg/zcjd/index.html','trs','.list li, .news_list li, .list-unstyled li',['wjw.hunan.gov.cn']),
 ('gd-policy','广东省卫生健康委员会','GD','policy','https://wsjkw.gd.gov.cn/hdjl/hdjl_zcwj/index.html','gd','.section.list li',['wsjkw.gd.gov.cn','www.nhc.gov.cn','www.gd.gov.cn']),
 ('gd-interpretation','广东省卫生健康委员会','GD','interpretation','https://wsjkw.gd.gov.cn/hdjl_zcjd/index.html','gd','.section.list li',['wsjkw.gd.gov.cn','www.nhc.gov.cn','www.gd.gov.cn']),
]
def seed(factory):
    with transaction(factory) as db:
        for id,name,region,kind,url,adapter,selector,hosts in SPECS:
            if not db.get(Source,id): db.add(Source(id=id,name=name,region=region,kind=kind,url=url,config={'adapter':adapter,'list_selector':selector,'body_selectors':COMMON_BODY,'hosts':hosts,'max_pages':3},enabled=False))
