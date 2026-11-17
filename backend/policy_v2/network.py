"""Worker-owned HTTP/Firefox sessions with public-host guards and pacing."""
import ipaddress
import re
import socket
import ssl
import time
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
    def __init__(self, settings):
        self.settings = settings
        self.last = {}
        self.last_mode = 'httpx'
        self.last_status = self.initial_status = None
        self._clients = {}
        self._playwright = self._browser = None
        self._contexts = {}

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

    def _http_client(self, host):
        # Hunan's TLS endpoint fails default EC negotiation (BAD_ECPOINT).
        # Pin the supported P-256 curve only for this host; retain CA/hostname checks.
        profile = 'hunan-p256' if host == 'wjw.hunan.gov.cn' else 'default'
        if profile not in self._clients:
            context = ssl.create_default_context()
            if profile == 'hunan-p256':
                context.set_ecdh_curve('prime256v1')
            self._clients[profile] = httpx.Client(verify=context, timeout=self.settings.fetch_timeout,
                                                trust_env=False, follow_redirects=False)
        return self._clients[profile]

    def validate(self, url, hosts):
        u = urlsplit(url)
        if u.scheme != 'https' or u.username or u.password or u.port not in (None, 443) or u.hostname not in hosts:
            raise FetchError('url_not_allowed')
        try:
            ips = {x[4][0] for x in socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)}
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
        self.last_mode = 'httpx'
        self.last_status = self.initial_status = None
        host = self.validate(url, hosts)
        # NHC HTML uses Firefox directly, including list_2.shtml and later pages.
        html = re.search(r'\.s?html?$', urlsplit(url).path, re.I)
        if host == 'www.nhc.gov.cn' and page_kind != 'attachment' and html:
            return self._get_firefox(url, hosts, page_kind, config)
        for _ in range(5):
            host = self.validate(url, hosts)
            self._pace(host)
            try:
                with self._http_client(host).stream('GET', url, headers={'User-Agent': 'WeiJianweiPolicyCollector/2.0', 'Accept': 'text/html,application/pdf,*/*'}) as response:
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
                    return b''.join(chunks), response.headers.get('content-type', 'application/octet-stream').split(';')[0], url
            except httpx.HTTPError as exc:
                raise FetchError(type(exc).__name__) from exc
        raise FetchError('redirect_limit')

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
                    return el && (el.textContent.trim().length >= 30 || el.querySelector('img[src],a[href]'));
                });
            }""", arg={'kind': kind, 'list': config['list_selector'], 'bodies': config['body_selectors']},
                timeout=self.settings.browser_ready_timeout * 1000)
            document = page.content()
            final_url = page.url
            self.validate(final_url, hosts)
            if navigation_count > 8:
                raise FetchError('redirect_limit')
            if final_response is None or final_response.url.split('#')[0] != final_url.split('#')[0]:
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
                if not any(body and (len(body.get_text(strip=True)) >= 30 or body.select('img[src],a[href]')) for body in bodies):
                    raise FetchError('body_not_ready')
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
