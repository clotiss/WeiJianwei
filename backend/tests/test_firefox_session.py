"""Real Firefox regression on a local fixture; no government-site traffic."""
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

import pytest

from policy_v2.network import SafeFetcher, FetchError
from policy_v2.settings import Settings


def test_firefox_reuses_cookie_and_waits_for_final_list_and_detail(monkeypatch):
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass
        def do_GET(self):
            seen.append((self.path, self.headers.get('Cookie', '')))
            status, headers, body = 200, {}, ''
            if self.path == '/list.shtml':
                status = 412
                headers['Set-Cookie'] = 'session=ready; Path=/'
                body = '<script>setTimeout(()=>location.replace("/list.shtml?ready=1"),100)</script>'
            elif self.path in ('/list.shtml?ready=1', '/list_2.shtml'):
                if 'session=ready' not in self.headers.get('Cookie', ''):
                    status, body = 403, 'missing session'
                else:
                    body = '<ul class="zxxx_list"><li>2026-11-17 <a href="/detail.shtml">Official policy title</a></li></ul><script src="/slow.js"></script><footer>List fully parsed</footer>'
            elif self.path == '/slow.js':
                time.sleep(0.3)
            elif self.path == '/detail.shtml':
                body = '<article id="article"></article><script>setTimeout(()=>document.querySelector("article").textContent="Official policy body, populated asynchronously after navigation.",200)</script>'
            elif self.path == '/blocked.shtml':
                status, body = 412, '<html>Not a policy page</html>'
            elif self.path == '/busy.shtml':
                status, headers, body = 429, {'Retry-After':'120'}, 'busy'
            self.send_response(status)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            for key, value in headers.items(): self.send_header(key, value)
            data = body.encode(); self.send_header('Content-Length', str(len(data))); self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
    base = f'http://127.0.0.1:{server.server_port}'
    config = {'list_selector':'.zxxx_list li', 'body_selectors':['#article'], 'hosts':['127.0.0.1']}
    fetcher = SafeFetcher(Settings(domain_delay_seconds=0, fetch_timeout=5, browser_ready_timeout=1))
    # Local fixture only; production public-HTTPS guards are tested separately.
    monkeypatch.setattr(fetcher, 'validate', lambda url, hosts: urlsplit(url).hostname)
    try:
        with fetcher:
            data, _, url = fetcher._get_firefox(base+'/list.shtml', config['hosts'], 'list', config)
            assert b'Official policy' in data and url.endswith('?ready=1')
            assert b'List fully parsed' in data
            assert (fetcher.initial_status, fetcher.last_status) == (412, 200)
            browser = fetcher._browser
            data, _, _ = fetcher._get_firefox(base+'/list_2.shtml', config['hosts'], 'list', config)
            assert b'Official policy' in data
            data, _, _ = fetcher._get_firefox(base+'/detail.shtml', config['hosts'], 'detail', config)
            assert b'populated asynchronously' in data
            assert fetcher._browser is browser and len(fetcher._contexts) == 1
            assert all(not c.pages for c in fetcher._contexts.values())
            with pytest.raises(FetchError, match='browser_content_timeout'):
                fetcher._get_firefox(base+'/blocked.shtml', config['hosts'], 'list', config)
            with pytest.raises(FetchError, match='http_429') as exc:
                fetcher._get_firefox(base+'/busy.shtml', config['hosts'], 'list', config)
            assert exc.value.retry_after == 120
        assert fetcher._browser is None and not fetcher._contexts
        assert ('/list_2.shtml', 'session=ready') in seen
    finally:
        fetcher.close(); server.shutdown(); server.server_close(); thread.join()
