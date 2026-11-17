"""Freeze reviewed public samples and deterministic parser expectations (no network)."""
import gzip
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from policy_v2.adapters import read_list
from policy_v2.parsing import parse_detail

ROOT=Path(__file__).resolve().parents[1]
FIXTURES=Path('backend/tests/fixtures/national')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,action='append',default=[],help='Merge additional reviewed trials after the retained final report.')
    args=parser.parse_args()
    sources_path=Path('backend/policy_v2/registry/sources.json');sources=json.loads(sources_path.read_text())
    reports={}
    for path in [Path('evidence/national/trials-final.json'),*args.report]:
        for row in json.loads(path.read_text()):reports[row['id']]=row
    manifest=[];FIXTURES.mkdir(parents=True,exist_ok=True)
    def raw(path):
        path=Path(path);data=path.read_bytes();return gzip.decompress(data) if path.suffix=='.gz' else data
    def freeze(data,id,label,extension='html'):
        path=FIXTURES/(id+'-'+label+'.'+extension+'.gz');path.write_bytes(gzip.compress(data,mtime=0))
        return str(path)
    for source in sources:
        if not source.get('config'):continue
        report=reports[source['id']];config=source['config'];items={}
        for n,page in enumerate(report['lists']):
            data=raw(page['path']);listing=read_list(data,page['url'],config)
            for item in listing.items:items[item['url']]=item
            page.update(count=len(listing.items),audit=listing.audit,next_url=listing.next_url)
            if n in (0,1,len(report['lists'])-1):
                fixture=freeze(data,source['id'],'list-'+str(n+1),'json' if config['adapter']=='government-json' else 'html');page['fixture']=fixture
                manifest.append(dict(source=source['id'],kind='list',fixture=fixture,url=page['url'],sha256=hashlib.sha256(data).hexdigest(),
                    expected={'items':listing.items,'next_url':listing.next_url,'audit':listing.audit}))
                if n==0:source['fixture']=fixture
        chosen=set();features=set()
        for n,detail in enumerate(report['details']):
            if not detail.get('path'):continue
            data=raw(detail['path']);item=items[detail['url']]
            try:
                parsed=parse_detail(data,detail['url'],item,SimpleNamespace(**source))
                if not parsed['published']:raise ValueError('publication_date_missing')
                detail.update(status='ok',title=parsed['title'],published=parsed['published'],body_chars=len(parsed['body']),
                    authority=parsed['authority'],kind=parsed['kind'],attachments=parsed['attachments'])
                detail.pop('error',None)
            except Exception as error:
                detail.update(status='error',error=str(error));continue
            available={('media' if a.get('media') else 'image' if a.get('image') else 'file') for a in parsed['attachments']}
            if n==0 or (available-features and len(chosen)<4) or (n==len(report['details'])-1 and len(chosen)<2):
                chosen.add(n);features|=available
                fixture=freeze(data,source['id'],'detail-'+str(n+1));detail['fixture']=fixture
                expected={k:parsed[k] for k in ['title','published','authority','kind','attachments']}
                expected.update(body_sha256=hashlib.sha256(parsed['body'].encode()).hexdigest(),body_chars=len(parsed['body']))
                manifest.append(dict(source=source['id'],kind='detail',fixture=fixture,url=detail['url'],item=item,
                    sha256=hashlib.sha256(data).hexdigest(),expected=expected))
        report['unique_items']=len(items);report['listing_exhausted']=not report['lists'][-1]['next_url']
        report['sample_ok']=sum(d['status']=='ok' for d in report['details'])
        report['status']='sample_pass' if report['sample_ok']==report['sample_target'] and not report['errors'] else 'needs_work'
        report['config_sha256']=hashlib.sha256(json.dumps(config,sort_keys=True).encode()).hexdigest()
        report['reparsed_at']=datetime.now(timezone.utc).isoformat()
        source['status']=report['status']
        source['validation']={k:report[k] for k in ['sample_ok','sample_target','unique_items','listing_exhausted','checked_at','config_sha256']}
        source['validation'].update(list_pages=len(report['lists']),mode='retained_public_samples',production_observation='pending')
        if source['region']=='HN':source['validation']['stability_note']='本轮样本通过；前轮发生 TLS EOF，仍需连续运行观察。'
    sources_path.write_text(json.dumps(sources,ensure_ascii=False,indent=2)+'\n')
    Path('evidence/national/trials-final.json').write_text(json.dumps(list(reports.values()),ensure_ascii=False,indent=2)+'\n')
    (FIXTURES/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'sources':len(reports),'sample_pass':sum(r['status']=='sample_pass' for r in reports.values()),
        'sample_documents':sum(r['sample_ok'] for r in reports.values()),'fixtures':len(manifest)},ensure_ascii=False))


if __name__=='__main__':main()
