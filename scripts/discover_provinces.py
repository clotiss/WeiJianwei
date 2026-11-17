"""Read-only inventory of official provincial homepage links; never enables a source."""
import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from policy_v2.network import SafeFetcher
from policy_v2.settings import Settings
from policy_v2.sources import source_definitions

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / 'backend/policy_v2/registry/provinces.json'


def inspect(row):
    url = row['homepage']
    result = {'region': row['region'], 'name': row['name'], 'url': url,
              'checked_at': datetime.now(timezone.utc).isoformat()}
    try:
        with SafeFetcher(Settings(fetch_timeout=15, max_download_bytes=4*1024*1024)) as fetcher:
            registered=next((s['config'] for s in source_definitions() if s['region']==row['region'] and s.get('config')), {})
            config={**registered,'body_selectors':['body'],'list_selector':'a[href]'}
            data, mime, final = fetcher.get(url, registered.get('hosts',[urlsplit(url).hostname]),page_kind='detail',config=config)
            result.update(http_status=fetcher.last_status, final_url=final)
        folder = ROOT / '.runtime/national/homepages';folder.mkdir(parents=True, exist_ok=True)
        (folder / (row['region']+'.html')).write_bytes(data)
        soup = BeautifulSoup(data, 'lxml')
        candidates=[];seen=set()
        for a in soup.select('a[href]'):
            label=a.get_text(' ',strip=True)
            if not label or len(label)>22 or not any(k in label for k in ['规范性','政策','解读','法规','政府信息公开','政务公开']):continue
            target=urljoin(final,a['href']);u=urlsplit(target)
            if u.scheme not in ('http','https') or (label,target) in seen:continue
            seen.add((label,target));candidates.append({'label':label,'url':target})
        result.update(status='homepage_read', title=soup.title.get_text(strip=True) if soup.title else '',
                      bytes=len(data),column_candidates=candidates)
    except Exception as error:
        cause=error
        while cause.__cause__ is not None:cause=cause.__cause__
        result.update(status='error',error=f'{type(cause).__name__}:{str(cause)[:300]}')
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--region',action='append')
    args=parser.parse_args()
    rows=json.loads(REGISTRY.read_text())
    rows=[r for r in rows if not args.region or r['region'] in args.region]
    output=ROOT/'evidence/national/homepages.json';output.parent.mkdir(parents=True,exist_ok=True)
    results=json.loads(output.read_text()) if output.exists() else []
    by_region={r['region']:r for r in results}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for future in as_completed([pool.submit(inspect,row) for row in rows]):
            result=future.result();by_region[result['region']]=result
            output.write_text(json.dumps(list(by_region.values()),ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
