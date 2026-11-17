"""Repeatable, read-only, per-domain live trials; retain raw bytes and failures."""
import argparse
import hashlib
import gzip
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit

from policy_v2.adapters import read_list
from policy_v2.network import SafeFetcher
from policy_v2.parsing import parse_detail
from policy_v2.settings import Settings
from policy_v2.sources import source_definitions, inventory
from probe_sources import describe_error

CACHE=Path('.runtime/national/trials')


def read(fetcher,url,source,kind,refresh=False):
    path=CACHE / (hashlib.sha256(url.encode()).hexdigest()+'.html')
    if path.exists() and not refresh:
        return path.read_bytes(),url,path,True
    config=source['config']
    # During adapter development save the DOM even when the body selector needs tuning.
    # Acceptance still requires parse_detail using the actual registered selector.
    transport={**config,'body_selectors':['body']} if kind=='detail' else config
    data,_,final=fetcher.get(url,config['hosts'],page_kind=kind,config=transport)
    path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    return data,final,path,False


def trial(source,fetcher,args):
    report={'id':source['id'],'region':source['region'],'url':source['url'],
            'config_sha256':hashlib.sha256(json.dumps(source['config'],sort_keys=True).encode()).hexdigest(),
            'checked_at':datetime.now(timezone.utc).isoformat(),'lists':[],'details':[],'errors':[]}
    url=source['url']; items={}; seen=set();config=source['config'];complete=False
    for n in range(args.pages):
        if not url or url in seen:break
        seen.add(url)
        try:
            fixture=source.get('fixture')
            if n==0 and fixture and Path(fixture).exists() and not args.refresh:
                path=Path(fixture);data=gzip.decompress(path.read_bytes()) if path.suffix=='.gz' else path.read_bytes();final=url;cached=True
            else:data,final,path,cached=read(fetcher,url,source,'list',args.refresh)
            listing=read_list(data,final,config)
            report['lists'].append({'url':final,'count':len(listing.items),'audit':listing.audit,
                'next_url':listing.next_url,'cached':cached,'path':str(path),'sha256':hashlib.sha256(data).hexdigest()})
            for item in listing.items:items[item['url']]=item
            url=listing.next_url;complete=not url
        except Exception as exc:
            report['errors'].append({'stage':'list','url':url,'error':describe_error(exc)});break
    report.update(unique_items=len(items),listing_exhausted=complete)
    selected=list(items.values())[:args.samples]
    failures=0
    for item in selected:
        detail={'url':item['url'],'list_title':item['title']}
        try:
            data,final,path,cached=read(fetcher,item['url'],source,'detail',args.refresh)
            detail.update(path=str(path),sha256=hashlib.sha256(data).hexdigest(),cached=cached)
            parsed=parse_detail(data,final,item,SimpleNamespace(**source))
            if not parsed['published']:raise ValueError('publication_date_missing')
            detail.update(status='ok',title=parsed['title'],published=parsed['published'],body_chars=len(parsed['body']),
                          authority=parsed['authority'],kind=parsed['kind'],attachments=parsed['attachments'])
        except Exception as exc:
            detail.update(status='error',error=describe_error(exc));failures+=1
            if 'path' not in detail:
                report['details'].append(detail)
                # Respect a failed upstream: no repeated burst through twenty documents.
                report['errors'].append({'stage':'transport','url':item['url'],'error':detail['error']})
                break
        report['details'].append(detail)
    report['sample_target']=min(args.samples,len(items)) if complete else args.samples;report['sample_ok']=sum(d['status']=='ok' for d in report['details'])
    report['status']='sample_pass' if selected and report['sample_ok']==report['sample_target'] and not report['errors'] else 'needs_work'
    print(json.dumps({k:report[k] for k in ('id','status','unique_items','sample_target','sample_ok','errors')},ensure_ascii=False),flush=True)
    return report


def run_group(sources,args):
    results=[]
    with SafeFetcher(Settings(fetch_timeout=25,browser_ready_timeout=20)) as fetcher:
        for source in sources:results.append(trial(source,fetcher,args))
    return results


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--region',action='append');parser.add_argument('--source',action='append')
    parser.add_argument('--batch',action='append',type=int,help='Province batch from the reviewed inventory; CN is batch 0')
    parser.add_argument('--samples',type=int,default=20);parser.add_argument('--pages',type=int,default=2)
    parser.add_argument('--refresh',action='store_true');parser.add_argument('--output',type=Path,default=Path('evidence/national/trials.json'))
    args=parser.parse_args();groups={}
    batches={p['region']:p['batch'] for p in inventory()};batches['CN']=0
    for s in source_definitions():
        if s.get('config') and (not args.region or s['region'] in args.region) and (not args.source or s['id'] in args.source) and (not args.batch or batches[s['region']] in args.batch):
            groups.setdefault(urlsplit(s['url']).hostname,[]).append(s)
    rows=json.loads(args.output.read_text()) if args.output.exists() else []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(run_group,g,args) for g in groups.values()]):
            fresh=future.result();ids={r['id'] for r in fresh};rows=[r for r in rows if r['id'] not in ids]+fresh
            args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
