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
            elif self.path == '/dynamic.shtml':
                body = '''<ul class="zxxx_list"><li>2026-11-17 <a href="/one.shtml">Official policy page 1</a></li></ul>
                <span class="current">1</span><a class="next" data-page="2" href="#">Next</a>
                <input class="jump"><button class="go" onclick="document.querySelector('.next').dataset.page=document.querySelector('.jump').value;document.querySelector('.next').click()">Go</button>
                <script>document.querySelector('.next').onclick=e=>{e.preventDefault();
                const n=Number(e.target.dataset.page);
                setTimeout(()=>{document.querySelector('li').innerHTML='2026-11-17 <a href="/'+n+'.shtml">Official policy page '+n+'</a>';
                setTimeout(()=>{document.querySelector('.current').textContent=n;e.target.dataset.page=n+1;},100);},100);};</script>'''
            elif self.path == '/embedded.shtml':
                body = '<article id="article"><iframe src="/file.pdf"></iframe></article>'
            elif self.path == '/media.shtml':
                body = '<article id="article"><video><source src="/movie.mp4"></video></article>'
            elif self.path == '/file.pdf':
                body = '%PDF-1.7 sample bytes with deliberately wrong content type'
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
            dynamic={**config,'browser_next':'.next','browser_current':'.current','browser_page_attribute':'data-page'}
            data,_,url=fetcher._get_firefox(base+'/dynamic.shtml#collector-page=3',config['hosts'],'list',dynamic)
            assert b'Official policy page 3' in data and url.endswith('#collector-page=3')
            data,_,_=fetcher._get_firefox(base+'/embedded.shtml',config['hosts'],'detail',config)
            assert b'iframe' in data
            data,_,_=fetcher._get_firefox(base+'/media.shtml',config['hosts'],'detail',config)
            assert b'video' in data
            jumping={**dynamic,'browser_jump_input':'.jump','browser_jump_submit':'.go'}
            data,_,url=fetcher._get_firefox(base+'/dynamic.shtml#collector-page=8',config['hosts'],'list',jumping)
            assert b'Official policy page 8' in data and url.endswith('#collector-page=8')
            binary={**config,'attachment_bootstrap_url':base+'/dynamic.shtml'}
            data,mime,_=fetcher._get_browser_attachment(base+'/file.pdf',config['hosts'],binary)
            assert data.startswith(b'%PDF') and mime=='application/pdf'
            fetcher.settings.max_download_bytes=10
            with pytest.raises(FetchError,match='browser_attachment_failed'):
                fetcher._get_browser_attachment(base+'/file.pdf',config['hosts'],binary)
        assert fetcher._browser is None and not fetcher._contexts
        assert ('/list_2.shtml', 'session=ready') in seen
    finally:
        fetcher.close(); server.shutdown(); server.server_close(); thread.join()
