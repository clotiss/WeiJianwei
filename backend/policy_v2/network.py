"""Worker-owned HTTP/Firefox sessions with public-host guards and pacing."""
import ipaddress
import base64
import re
import socket
import ssl
import time
from contextlib import ExitStack
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from playwright.sync_api import Error as BrowserError, TimeoutError as BrowserTimeout, sync_playwright


class FetchError(Exception):
    def __init__(self, message, retry_after=None):
        super().__init__(message)
        self.retry_after = retry_after


def retry_after_seconds(value, now=None):
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        try:
            seconds = parsedate_to_datetime(value).timestamp() - (time.time() if now is None else now)
        except (TypeError, ValueError, OverflowError):
            return None
    return max(0, seconds) if seconds < float('inf') else None


class SafeFetcher:
    """Use one instance per sequential worker; close it at worker shutdown."""
    def __init__(self, settings, factory=None):
        self.settings = settings
        self.factory = factory
        self.last = {}
        self.last_mode = 'httpx'
        self.last_status = self.initial_status = None
        self._clients = {}
        self._playwright = self._browser = None
        self._contexts = {}
        self._public_http_hosts = frozenset()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        try:
            if self._browser:
                self._browser.close()
        finally:
            self._contexts.clear()
            self._browser = None
            if self._playwright:
                self._playwright.stop()
                self._playwright = None
            for client in self._clients.values():
                client.close()
            self._clients.clear()

    def _http_client(self, host, config=None):
        curve = (config or {}).get('tls_curve')
        profile = curve or 'default'
        if profile not in self._clients:
            context = ssl.create_default_context()
            if curve:
                context.set_ecdh_curve(curve)
            self._clients[profile] = httpx.Client(verify=context, timeout=self.settings.fetch_timeout,
                                                trust_env=False, follow_redirects=False)
        return self._clients[profile]

    def validate(self, url, hosts):
        u = urlsplit(url)
        public_http=u.scheme=='http' and u.hostname in self._public_http_hosts
        port=80 if public_http else 443
        if (u.scheme!='https' and not public_http) or u.username or u.password or u.port not in (None,port) or u.hostname not in hosts:
            raise FetchError('url_not_allowed')
        try:
            ips = {x[4][0] for x in socket.getaddrinfo(u.hostname,port,type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise FetchError('dns_failed') from exc
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
            raise FetchError('non_public_address')
        return u.hostname

    def _pace(self, host):
        previous = self.last.get(host)
        if previous is not None:
            delay = self.settings.domain_delay_seconds - (time.monotonic() - previous)
            if delay > 0:
                time.sleep(delay)
        self.last[host] = time.monotonic()

    def get(self, url, hosts, *, page_kind=None, config=None):
        # A reviewed public HTTP exception applies only to this source request,
        # including redirects/resources; it never disables HTTPS verification.
        previous=self._public_http_hosts
        self._public_http_hosts=frozenset((config or {}).get('public_http_hosts',[])) & frozenset(hosts)
        try:return self._get_guarded(url,hosts,page_kind=page_kind,config=config)
        finally:self._public_http_hosts=previous

    def _get_guarded(self,url,hosts,*,page_kind=None,config=None):
        if self.factory is None:
            return self._get(url, hosts, page_kind=page_kind, config=config)
        from .domains import lease, cool_down
        self.validate(url, hosts)
        # Reserve reviewed redirect/resource hosts too. Sorted, nonblocking acquisition
        # prevents deadlock and cross-worker overlap after a same-source redirect.
        with ExitStack() as leases:
            for host in sorted(set(hosts)):
                leases.enter_context(lease(self.factory,host,self.settings.domain_delay_seconds,self.settings.task_lease_seconds))
            try:return self._get(url, hosts, page_kind=page_kind, config=config)
            except Exception as exc:
                # Persist the initial cooldown before releasing the domain leases;
                # pipeline health tracking subsequently extends exponential backoff.
                cool_down(self.factory,hosts,max(self.settings.source_cooldown_seconds,getattr(exc,'retry_after',None) or 0))
                raise

    def _get(self, url, hosts, *, page_kind=None, config=None):
        self.last_mode = 'httpx'
        self.last_status = self.initial_status = None
        host = self.validate(url, hosts)
        if page_kind=='attachment' and (config or {}).get('attachment_transport')=='firefox':
            return self._get_browser_attachment(url,hosts,config)
        if (config or {}).get('transport') == 'firefox' and page_kind != 'attachment':
            return self._get_firefox(url, hosts, page_kind, config)
        for _ in range(5):
            host = self.validate(url, hosts)
            self._pace(host)
            try:
                with self._http_client(host, config).stream('GET', url, headers={'User-Agent': 'WeiJianweiPolicyCollector/2.0', 'Accept': 'text/html,application/pdf,*/*'}) as response:
                    self.last_status = response.status_code
                    if self.initial_status is None:
                        self.initial_status = self.last_status
                    if self.last_status in (301, 302, 303, 307, 308):
                        url = urljoin(url, response.headers.get('location', ''))
                        continue
                    if self.last_status != 200:
                        raise FetchError(f'http_{self.last_status}', retry_after_seconds(response.headers.get('Retry-After')))
                    if int(response.headers.get('content-length', '0')) > self.settings.max_download_bytes:
                        raise FetchError('download_too_large')
                    chunks, total = [], 0
                    for chunk in response.iter_bytes():
                        total += len(chunk)
                        if total > self.settings.max_download_bytes:
                            raise FetchError('download_too_large')
                        chunks.append(chunk)
                    data=b''.join(chunks)
                    mime=response.headers.get('content-type','application/octet-stream').split(';')[0]
                    if page_kind=='attachment':mime=self._check_attachment(data,mime)
                    return data,mime,url
            except httpx.HTTPError as exc:
                raise FetchError(type(exc).__name__) from exc
        raise FetchError('redirect_limit')

    @staticmethod
    def _check_attachment(data,mime):
        signatures=((b'%PDF-','application/pdf'),(b'PK\x03\x04','application/zip'),
                    (b'\xd0\xcf\x11\xe0','application/octet-stream'),(b'\x89PNG','image/png'),
                    (b'\xff\xd8\xff','image/jpeg'),(b'GIF8','image/gif'))
        for signature,actual in signatures:
            if data.startswith(signature):return actual
        if mime in ('text/html','application/xhtml+xml') or data.lstrip().lower().startswith((b'<!doctype html',b'<html')):
            raise FetchError('attachment_returned_html')
        return mime

    def _get_browser_attachment(self,url,hosts,config):
        """Read a bounded binary stream using the site's verified Firefox session."""
        bootstrap=config['attachment_bootstrap_url'];self.validate(bootstrap,hosts)
        page=self._browser_context(bootstrap,hosts).new_page();self.last_mode='firefox'
        try:
            try:page.goto(bootstrap,wait_until='domcontentloaded',timeout=self.settings.fetch_timeout*1000)
            except BrowserError:pass  # The challenge may navigate; readiness below must still pass.
            page.locator(config['list_selector']).first.wait_for(state='attached',timeout=self.settings.browser_ready_timeout*1000)
            self.validate(page.url,hosts)
            self._pace(urlsplit(url).hostname)
            result=page.evaluate("""async ({url,limit,timeout})=>{
                const response=await fetch(url,{signal:AbortSignal.timeout(timeout)});
                if(!response.ok) return {status:response.status,retry:response.headers.get('retry-after')};
                const reader=response.body.getReader();let size=0;const chunks=[];
                while(true){const {done,value}=await reader.read();if(done)break;
                    size+=value.length;if(size>limit){await reader.cancel();throw Error('download_too_large');}chunks.push(value);}
                let binary='';for(const chunk of chunks)for(let i=0;i<chunk.length;i+=32768)
                    binary+=String.fromCharCode(...chunk.subarray(i,i+32768));
                return {status:response.status,url:response.url,mime:response.headers.get('content-type')||'application/octet-stream',data:btoa(binary)};
            }""",{'url':url,'limit':self.settings.max_download_bytes,'timeout':self.settings.fetch_timeout*1000})
            self.last_status=result['status']
            if result['status']!=200:raise FetchError('http_'+str(result['status']),retry_after_seconds(result.get('retry')))
            self.validate(result['url'],hosts);data=base64.b64decode(result['data']);mime=result['mime'].split(';')[0]
            mime=self._check_attachment(data,mime)
            return data,mime,result['url']
        except BrowserError as exc:raise FetchError('browser_attachment_failed') from exc
        finally:page.close()

    def _browser_context(self, url, hosts):
        key = (urlsplit(url).netloc, tuple(sorted(hosts)))
        if self._browser is None:
            self._playwright = sync_playwright().start()
            self._browser = self._playwright.firefox.launch(headless=True)
        if key not in self._contexts:
            context = self._browser.new_context(locale='zh-CN', service_workers='block')
            # Use the installed Firefox's native UA and navigation headers.
            def guard(route):
                request = route.request
                try:
                    host = self.validate(request.url, hosts)
                    if request.is_navigation_request() and request.frame == request.frame.page.main_frame:
                        self._pace(host)
                except (FetchError, ValueError):
                    route.abort()
                    return
                route.continue_()
            context.route('**/*', guard)
            self._contexts[key] = context
        return self._contexts[key]

    def _get_firefox(self, url, hosts, page_kind=None, config=None):
        from .sources import COMMON_BODY
        from .parsing import parse_list, ParseError
        config = config or {'list_selector': '.zxxx_list li', 'hosts': hosts, 'body_selectors': COMMON_BODY}
        kind = page_kind or ('list' if re.search(r'/list(?:_\d+)?\.shtml$', urlsplit(url).path) else 'detail')
        requested_page=1
        if (config.get('browser_next') or config.get('browser_jump_input')) and kind=='list':
            cursor=re.fullmatch(r'collector-page=(\d+)',urlsplit(url).fragment)
            requested_page=int(cursor[1]) if cursor else 1
            if not 1 <= requested_page <= 100: raise FetchError('browser_page_limit')
            url=url.split('#')[0]
        self.last_mode = 'firefox'
        page = None
        final_response = None
        navigation_count = 0
        try:
            page = self._browser_context(url, hosts).new_page()
            def observe(response):
                nonlocal final_response, navigation_count
                if response.request.is_navigation_request() and response.frame == page.main_frame:
                    navigation_count += 1
                    if self.initial_status is None:
                        self.initial_status = response.status
                    final_response = response
                    self.last_status = response.status
            page.on('response', observe)
            try:
                page.goto(url, wait_until='domcontentloaded', timeout=self.settings.fetch_timeout * 1000)
            except BrowserError:
                # A client-side navigation may interrupt Firefox's initial goto.
                # Only a response followed by a validated DOM can recover it.
                if final_response is None:
                    raise
            if final_response is not None and final_response.status in (403, 429, 503):
                raise FetchError(f'http_{final_response.status}', retry_after_seconds(final_response.headers.get('retry-after')))
            page.wait_for_function("""({kind, list, bodies}) => {
                if (document.readyState === 'loading') return false;
                if (kind === 'list') return Array.from(document.querySelectorAll(list)).some(
                    row => row.querySelector('a[href]') && /(?:19|20)\\d{2}[-年/.]\\d{1,2}[-月/.]\\d{1,2}/.test(row.textContent));
                return bodies.some(selector => {
                    const el = document.querySelector(selector);
                    return el && (el.textContent.trim().length >= 30 || el.querySelector('img[src],a[href],iframe[src],embed[src],object[data],video,audio'));
                });
            }""", arg={'kind': kind, 'list': config['list_selector'], 'bodies': config['body_selectors']},
                timeout=self.settings.browser_ready_timeout * 1000)
            if config.get('browser_ready_selector') and kind=='list':
                page.locator(config['browser_ready_selector']).first.wait_for(state='attached',timeout=self.settings.browser_ready_timeout*1000)
            steps=[requested_page-1] if requested_page>1 and config.get('browser_jump_input') else range(1,requested_page)
            for current in steps:
                before=page.locator(config['list_selector']).all_text_contents()
                self._pace(urlsplit(url).hostname)
                if config.get('browser_jump_input'):
                    page.locator(config['browser_jump_input']).fill(str(requested_page))
                    page.locator(config['browser_jump_submit']).click(timeout=self.settings.browser_ready_timeout*1000)
                else:
                    page.locator(config['browser_next']).first.click(timeout=self.settings.browser_ready_timeout*1000)
                page.wait_for_function("""({selector,before}) => {
                    const rows=Array.from(document.querySelectorAll(selector));
                    return rows.length>0 && JSON.stringify(rows.map(el=>el.textContent))!==JSON.stringify(before);
                }""",arg={'selector':config['list_selector'],'before':before},timeout=self.settings.browser_ready_timeout*1000)
                if config.get('browser_current'):
                    page.wait_for_function("""({selector,expected}) =>
                        document.querySelector(selector)?.textContent.trim() === String(expected)
                    """,arg={'selector':config['browser_current'],'expected':current+1},timeout=self.settings.browser_ready_timeout*1000)
            document = page.content()
            final_url = page.url
            self.validate(final_url, hosts)
            if navigation_count > 8:
                raise FetchError('redirect_limit')
            history_update=(config.get('allow_history_url_update') and final_response is not None
                and urlsplit(final_response.url)[:3]==urlsplit(final_url)[:3])
            if final_response is None or (final_response.url.split('#')[0] != final_url.split('#')[0] and not history_update):
                raise FetchError('navigation_not_settled')
            self.last_status = final_response.status
            if self.last_status not in (200, 412):
                raise FetchError(f'http_{self.last_status}', retry_after_seconds(final_response.headers.get('retry-after')))
            content = document.encode('utf-8')
            if len(content) > self.settings.max_download_bytes:
                raise FetchError('download_too_large')
            if kind == 'list':
                parse_list(content, final_url, config)
            else:
                soup = BeautifulSoup(document, 'lxml')
                bodies = [soup.select_one(selector) for selector in config['body_selectors']]
                if not any(body and (len(body.get_text(strip=True)) >= 30 or body.select('img[src],a[href],iframe[src],embed[src],object[data],video,audio')) for body in bodies):
                    raise FetchError('body_not_ready')
            if requested_page>1:final_url += '#collector-page='+str(requested_page)
            return content, 'text/html', final_url
        except BrowserTimeout as exc:
            raise FetchError('browser_content_timeout') from exc
        except BrowserError as exc:
            raise FetchError('browser_navigation_failed') from exc
        except ParseError as exc:
            raise FetchError('list_not_ready') from exc
        finally:
            if page is not None:
                try:
                    page.close()
                except BrowserError:
                    pass
