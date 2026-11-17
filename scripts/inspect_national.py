"""Fetch explicitly discovered URLs, sequentially per province, with local evidence."""
import argparse
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from policy_v2.network import SafeFetcher
from policy_v2.settings import Settings
from probe_sources import describe_error


def inspect(group):
    results = []
    with SafeFetcher(Settings(fetch_timeout=20)) as fetcher:
        for target in group:
            row = {**target, 'checked_at': datetime.now(timezone.utc).isoformat()}
            try:
                data, mime, final = fetcher.get(target['url'], target.get('hosts') or [urlsplit(target['url']).hostname],
                    page_kind=target.get('page_kind'), config=target.get('config'))
                path = Path('.runtime/national/pages') / (target['id'] + '.html')
                path.parent.mkdir(parents=True, exist_ok=True); path.write_bytes(data)
                dom = BeautifulSoup(data, 'lxml')
                links = []
                for a in dom.select('a[href]'):
                    label = a.get_text(' ', strip=True)
                    if any(w in label for w in ['规范性', '政策', '解读', '法规', '政务公开', '政府信息公开', '下一页']):
                        url = urljoin(final, a['href'])
                        if len(label) < 30 and url.startswith(('http://', 'https://')):
                            link = {'label': label, 'url': url}
                            if link not in links: links.append(link)
                row.update(status='read', http_status=fetcher.last_status, final_url=final, bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), path=str(path),
                           title=dom.title.get_text(strip=True) if dom.title else '', links=links)
            except Exception as exc:
                row.update(status='error', error=describe_error(exc))
            print(json.dumps({k:v for k,v in row.items() if k not in ('links','config')}, ensure_ascii=False), flush=True)
            results.append(row)
    return results


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('targets',type=Path)
    parser.add_argument('--output',type=Path,default=Path('evidence/national/inspections.json'))
    args=parser.parse_args(); targets=json.loads(args.targets.read_text()); groups={}
    for t in targets:groups.setdefault(urlsplit(t['url']).hostname,[]).append(t)
    rows=json.loads(args.output.read_text()) if args.output.exists() else []
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(inspect,g) for g in groups.values()]):
            new=future.result(); ids={r['id'] for r in new}; rows=[r for r in rows if r['id'] not in ids]+new
            args.output.parent.mkdir(parents=True,exist_ok=True)
            args.output.write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')


if __name__=='__main__':main()
