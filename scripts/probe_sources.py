import json,time
from pathlib import Path
from urllib.parse import urljoin
import httpx
from bs4 import BeautifulSoup
urls={'js-policy':'https://wjw.jiangsu.gov.cn/col/col7408/index.html','hn-home':'https://wjw.hunan.gov.cn/','gd-policy':'https://wsjkw.gd.gov.cn/hdjl/hdjl_zcwj/index.html','gd-interpretation':'https://wsjkw.gd.gov.cn/hdjl_zcjd/index.html','nhc-policy':'https://www.nhc.gov.cn/wjw/gfxwjj/list.shtml','nhc-interpretation':'https://www.nhc.gov.cn/wjw/zcjd/list.shtml'}
manifest={}
for name,url in urls.items():
 try:
  r=httpx.get(url,timeout=20,follow_redirects=True,headers={'User-Agent':'Mozilla/5.0'})
  manifest[name]={'url':str(r.url),'status':r.status_code,'bytes':len(r.content),'at':time.time()}
  if r.status_code==200:
   Path(f'evidence/sources/{name}.html').write_bytes(r.content)
   s=BeautifulSoup(r.content,'lxml')
   print(name,[(a.get_text(' ',strip=True)[:50],urljoin(str(r.url),a['href'])) for a in s.select('a[href]') if any(w in a.get_text() for w in ['政策','规范性','解读'])][:18],flush=True)
  else:print(name,r.status_code,flush=True)
 except Exception as e:manifest[name]={'url':url,'error':type(e).__name__};print(name,type(e).__name__,flush=True)
Path('evidence/sources/manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
