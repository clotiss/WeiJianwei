"""Registered public HTTPS sources only. Redirects and DNS checked at each request."""
import ipaddress
import socket
import time
from urllib.parse import urlsplit,urljoin
import httpx

class FetchError(Exception): pass

class SafeFetcher:
    def __init__(self,settings): self.settings=settings;self.last={}
    def validate(self,url,hosts):
        u=urlsplit(url)
        if u.scheme!='https' or u.username or u.password or u.port not in (None,443) or u.hostname not in hosts: raise FetchError('url_not_allowed')
        try: ips={x[4][0] for x in socket.getaddrinfo(u.hostname,443,type=socket.SOCK_STREAM)}
        except OSError as e: raise FetchError('dns_failed') from e
        if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips): raise FetchError('non_public_address')
        return u.hostname
    def get(self,url,hosts):
        for _ in range(5):
            host=self.validate(url,hosts)
            delay=self.settings.domain_delay_seconds-(time.monotonic()-self.last.get(host,0))
            if delay>0:time.sleep(delay)
            self.last[host]=time.monotonic()
            try:
                with httpx.Client(timeout=self.settings.fetch_timeout,trust_env=False,follow_redirects=False) as client:
                    with client.stream('GET',url,headers={'User-Agent':'WeiJianweiPolicyCollector/2.0','Accept':'text/html,application/pdf,*/*'}) as r:
                        if r.status_code in (301,302,303,307,308): url=urljoin(url,r.headers.get('location',''));continue
                        if r.status_code==429: raise FetchError('rate_limited:'+r.headers.get('Retry-After','60')[:20])
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
