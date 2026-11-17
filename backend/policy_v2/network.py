"""Registered public HTTPS sources only. Redirects and DNS checked at each request."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit,urljoin
import httpx
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

class FetchError(Exception): pass

class SafeFetcher:
    def __init__(self,settings): self.settings=settings;self.last={};self.last_mode='httpx';self.last_status=None
    def validate(self,url,hosts):
        u=urlsplit(url)
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.hostname not in hosts: raise FetchError('url_not_allowed')
        try: ips={x[4][0] for x in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)}
        except OSError as e: raise FetchError('dns_failed') from e
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips): raise FetchError('non_public_address')
        return u.hostname
    def get(self,url,hosts):
        self.last_mode='httpx';self.last_status=None
        for _ in range(5):
            host=self.validate(url,hosts)
            delay=self.settings.domain_delay_seconds-(time.monotonic()-self.last.get(host,0))
            if delay>0:time.sleep(delay)
            self.last[host]=time.monotonic()
            try:
                with httpx.Client(timeout=self.settings.fetch_timeout,trust_env=False,follow_redirects=False) as client:
                    with client.stream('GET',url,headers={'User-Agent':'WeiJianweiPolicyCollector/2.0','Accept':'text/html,application/pdf,*/*'}) as r:
                        self.last_mode='httpx';self.last_status=r.status_code
                        if r.status_code in (301,302,303,307,308): url=urljoin(url,r.headers.get('location',''));continue
                        if r.status_code==429: raise FetchError('rate_limited:'+r.headers.get('Retry-After','60')[:20])
                        if r.status_code==412 and host=='www.nhc.gov.cn':
                            return self._get_firefox(url,hosts)
                        if r.status_code!=200: raise FetchError(f'http_{r.status_code}')
                        if int(r.headers.get('content-length','0'))>self.settings.max_download_bytes:raise FetchError('download_too_large')
                        chunks=[];total=0
                        for c in r.iter_bytes():
                            total+=len(c)
                            if total>self.settings.max_download_bytes:raise FetchError('download_too_large')
                            chunks.append(c)
                        return b''.join(chunks),r.headers.get('content-type','application/octet-stream').split(';')[0],url
            except httpx.HTTPError as e: raise FetchError(type(e).__name__) from e
        raise FetchError('redirect_limit')

    def _get_firefox(self,url,hosts):
        """Retry the NHC WZWS response in Firefox, accepting 412 only for a real article DOM."""
        host=self.validate(url,hosts)
        headers={
            'Accept':'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language':'zh-CN,zh;q=0.9,en;q=0.8',
            'Accept-Encoding':'gzip, deflate, br',
            'Cache-Control':'no-cache',
            'Sec-Fetch-Dest':'document','Sec-Fetch-Mode':'navigate','Sec-Fetch-Site':'none',
            'Sec-Fetch-User':'?1','Upgrade-Insecure-Requests':'1',
        }
        with sync_playwright() as playwright:
            browser=playwright.firefox.launch(headless=True)
            try:
                context=browser.new_context(
                    user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:132.0) Gecko/20100101 Firefox/132.0',
                    locale='zh-CN')
                context.set_extra_http_headers(headers)

                def guard(route):
                    request_url=route.request.url
                    scheme=urlsplit(request_url).scheme
                    if scheme in ('http','https'):
                        try: self.validate(request_url,hosts)
                        except FetchError: route.abort();return
                    route.continue_()

                context.route('**/*',guard)
                page=context.new_page()
                response=page.goto(url,wait_until='domcontentloaded',timeout=self.settings.fetch_timeout*1000)
                if response is None: raise FetchError('firefox_no_response')
                status=response.status
                self.last_mode='firefox';self.last_status=status
                if urlsplit(url).path.endswith('list.shtml'):
                    try: page.wait_for_selector('.zxxx_list li',timeout=min(10000,self.settings.fetch_timeout*1000))
                    except Exception: pass
                else:
                    page.wait_for_timeout(min(2000,self.settings.fetch_timeout*1000))
                document=page.content()
                content=document.encode('utf-8')
                mime=response.headers.get('content-type','text/html').split(';')[0]
                if status==412 and host=='www.nhc.gov.cn':
                    soup=BeautifulSoup(document,'lxml')
                    has_list=bool(soup.select('.zxxx_list li'))
                    has_body=False
                    for selector in ('#UCAP-CONTENT','#xw_box','.TRS_Editor','.article-content','.article_cont','.content-text','#content'):
                        body=soup.select_one(selector)
                        if body and len(body.get_text(' ',strip=True))>=100:
                            has_body=True;break
                    if has_list or has_body: return content,mime,page.url
                if status!=200: raise FetchError(f'http_{status}')
                return content,mime,page.url
            finally:
                browser.close()
