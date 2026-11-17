"""Reviewed registry data is separate from transport and parser implementations."""
import json
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit
from .models import Source
from .db import transaction

REGISTRY = Path(__file__).with_name('registry')
COMMON_BODY = ['#UCAP-CONTENT','#xw_box','.TRS_Editor','#zoom','.article-content',
               '.article_cont','.content-text','.content-content','.main-fl.bt-left','#content']

def inventory():
    return json.loads((REGISTRY / 'provinces.json').read_text())

def source_definitions():
    rows = json.loads((REGISTRY / 'sources.json').read_text())
    seen = set()
    regions = {'CN', *(p['region'] for p in inventory())}
    for row in rows:
        if row['id'] in seen or row['region'] not in regions:
            raise ValueError('invalid_source_identity:' + row['id'])
        seen.add(row['id'])
        if not row.get('config'): continue
        config = row['config']; url = urlsplit(row['url'])
        public_http=url.scheme=='http' and url.hostname in config.get('public_http_hosts',[])
        if (url.scheme!='https' and not public_http) or url.hostname not in config['hosts']:
            raise ValueError('invalid_source_url:' + row['id'])
        if not set(config.get('public_http_hosts',[])).issubset(config['hosts']):
            raise ValueError('invalid_public_http_hosts:'+row['id'])
        if not set(config.get('list_hosts', [])).issubset(config['hosts']):
            raise ValueError('invalid_list_hosts:' + row['id'])
        if config.get('transport', 'http') not in ('http', 'firefox'):
            raise ValueError('invalid_transport:' + row['id'])
        if config.get('attachment_transport','http') not in ('http','firefox'):
            raise ValueError('invalid_attachment_transport:'+row['id'])
        if config.get('attachment_transport')=='firefox':
            bootstrap=urlsplit(config.get('attachment_bootstrap_url',''))
            if bootstrap.scheme!='https' or bootstrap.hostname not in config['hosts']:
                raise ValueError('invalid_attachment_bootstrap:'+row['id'])
        if not 1<=int(config.get('max_pages',3))<=100:
            raise ValueError('invalid_page_limit:'+row['id'])
    return rows

DEFINITIONS = source_definitions()
BY_ID = {row['id']: row for row in DEFINITIONS}
# Compatibility for operational scripts; behavior lives in registry data.
SPECS = [(r['id'], r['name'], r['region'], r['kind'], r['url'], r['config']['adapter'],
          r['config']['list_selector'], r['config']['hosts']) for r in DEFINITIONS if r.get('config')]

def source_config(spec):
    return deepcopy(BY_ID[spec[0]]['config'])

def seed(factory):
    with transaction(factory) as db:
        for row in source_definitions():
            if not row.get('config'): continue
            values = {key: row[key] for key in ('name','region','kind','url','config')}
            source = db.get(Source, row['id'])
            if source is None:
                db.add(Source(id=row['id'], **values, enabled=False))
            else:
                for key, value in values.items():
                    setattr(source, key, value)
