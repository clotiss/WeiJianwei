"""Read-only representative attachment download, storage and extraction checks."""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from policy_v2.network import SafeFetcher
from policy_v2.parsing import parse_detail
from policy_v2.extraction import extract
from policy_v2.settings import Settings
from policy_v2.sources import source_definitions
from policy_v2.storage import make_store
from probe_sources import describe_error


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report',type=Path,default=Path('evidence/national/trials-final.json'))
    parser.add_argument('--output',type=Path,default=Path('evidence/national/attachments.json'))
    args=parser.parse_args();definitions={s['id']:s for s in source_definitions()};selected={};groups={}
    for report in json.loads(args.report.read_text()):
        source=definitions[report['id']]
        for detail in report['details']:
            if not detail.get('path'):continue
            try:parsed=parse_detail(Path(detail['path']).read_bytes(),detail['url'],{'title':detail['list_title'],'published':detail.get('published')},SimpleNamespace(**source))
            except Exception:continue
            for attachment in parsed['attachments']:
                if attachment['status']!='pending':continue
                family='image' if attachment.get('image') else 'file'
                key=(source['region'],family)
                if key not in selected:
                    selected[key]=(source,detail,attachment);groups.setdefault(urlsplit(attachment['url']).hostname,[]).append(selected[key])
    settings=Settings(fetch_timeout=25,object_root=Path('.runtime/national/attachment-objects'))
    store=make_store(settings)
    def group(items):
        rows=[]
        with SafeFetcher(settings) as fetcher:
            for source,detail,attachment in items:
                row={'source':source['id'],'region':source['region'],'article':detail['url'],'url':attachment['url'],'checked_at':datetime.now(timezone.utc).isoformat()}
                try:
                    data,mime,final=fetcher.get(attachment['url'],source['config']['hosts'],page_kind='attachment',config=source['config'])
                    if mime in ('text/html','application/xhtml+xml') or data.lstrip().lower().startswith((b'<!doctype html',b'<html')):raise ValueError('attachment_returned_html')
                    saved=store.put(data,mime);blocks,status=extract(data,final)
                    row.update(status='stored',extraction=status,bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),object_key=saved['key'],blocks=len(blocks),mime=mime)
                except Exception as exc:row.update(status='error',error=describe_error(exc))
                rows.append(row);print(json.dumps({k:row[k] for k in ('source','status','extraction','bytes','error') if k in row},ensure_ascii=False),flush=True)
                if row['status']=='error':break  # Do not burst retries against the same failed domain.
        return rows
    results=[]
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(group,items) for items in groups.values()]):
            results.extend(future.result());args.output.write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
