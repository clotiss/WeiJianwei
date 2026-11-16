import re
import unicodedata
from datetime import date
from urllib.parse import urljoin,urlsplit,urlunsplit
from bs4 import BeautifulSoup

class ParseError(Exception): pass

def canonical(url):
    u=urlsplit(url)
    return urlunsplit((u.scheme.lower(),u.netloc.lower(),u.path,u.query,''))
def date_value(text):
    m=re.search(r'(20\d{2}|19\d{2})[-年/.](\d{1,2})[-月/.](\d{1,2})',text or '')
    if not m:return None
    try:return date(*map(int,m.groups())).isoformat()
    except ValueError:return None

def soup(data): return BeautifulSoup(data,'lxml')
def clean(text):return re.sub(r'[ \t\r\f\v]+',' ',unicodedata.normalize('NFKC',text)).strip()
def parse_list(data,url,config):
    s=soup(data)
    # JCMS servers may embed item HTML in script text / XML records rather than live DOM.
    for fragment in re.findall(r'<!\[CDATA\[(.*?)\]\]>',data.decode('utf-8',errors='replace'),re.S):
        s.append(soup(fragment))
    rows=s.select(config['list_selector']);items=[];seen=set()
    for row in rows:
        a=row.select_one('a[href]')
        if not a:continue
        target=canonical(urljoin(url,a['href']));title=clean(a.get('title') or a.get_text(' ',strip=True))
        if len(title)<6 or target in seen or not re.search(r'\.(?:s?html?|shtm)(?:\?|$)',target,re.I):continue
        if urlsplit(target).hostname not in config['hosts']:continue
        published=date_value(row.get_text(' ',strip=True))
        if not published:continue # Menu links are not list items; never fabricate publication dates.
        seen.add(target);items.append({'url':target,'title':title,'published':published})
    if not items:raise ParseError('list_empty_or_selector_changed')
    next_url=None
    for a in s.select('a[href]'):
        if a.get_text(strip=True) in ('下一页','下页','>','下一页 >'):
            candidate=canonical(urljoin(url,a['href']))
            if candidate!=url and urlsplit(candidate).hostname in config['hosts']:next_url=candidate;break
    return items,next_url

def page_url(first,n,adapter):
    if n==1:return first
    if adapter=='nhc':return first.replace('list.shtml',f'list_{n}.shtml')
    if adapter in ('trs','gd'):return first.replace('index.html',f'index_{n-1}.html')
    return None # JCMS pagination must use discovered links / tested source configuration.

def parse_detail(data,url,item,source):
    s=soup(data)
    def meta(name):
        el=s.find('meta',attrs={'name':re.compile('^'+name+'$',re.I)})
        return el.get('content','') if el else ''
    title=clean(meta('ArticleTitle') or item.get('title') or '')
    body_el=None
    for selector in source.config['body_selectors']:
        el=s.select_one(selector)
        if el and (len(el.get_text(strip=True))>=30 or el.select('a[href],img')):body_el=el;break
    if body_el is None:raise ParseError('body_selector_missing')
    for tag in body_el.select('script,style,iframe,form,button'):tag.decompose()
    body=clean(body_el.get_text('\n',strip=True))
    attachments=[]
    for a in body_el.select('a[href]'):
        href=canonical(urljoin(url,a['href']))
        if re.search(r'\.(pdf|docx?|xlsx?)(?:$|[?#])',href,re.I):
            attachments.append({'name':a.get_text(' ',strip=True) or urlsplit(href).path.rsplit('/',1)[-1],'url':href,'status':'pending'})
    # Image-only official interpretations are retained as image attachments; OCR is explicit, not invented text.
    for a in body_el.select('img[src]'):
        attachments.append({'name':a.get('alt') or '正文图片','url':canonical(urljoin(url,a['src'])),'status':'pending','image':True})
    if len(body)<30 and not attachments:raise ParseError('body_empty')
    published=date_value(meta('PubDate') or meta('pubdate')) or item.get('published')
    authority=clean(meta('ContentSource') or source.name)
    num=re.search(r'[\u4e00-\u9fff]{1,12}(?:\([^)]{1,10}\))?[〔\[【](?:19|20)\d{2}[〕\]】]\s*\d+\s*号',body)
    excluded=any(w in title for w in ['征求意见','公开征集','招聘','拟聘','会议召开','召开会议'])
    kind='excluded' if excluded else source.kind
    links=[{'url':canonical(urljoin(url,a['href'])),'text':a.get_text(' ',strip=True)} for a in body_el.select('a[href]') if any(w in a.get_text() for w in ['解读','政策原文','相关文件'])]
    return dict(title=title,body=body,authority=authority,published=published,doc_number=num.group(0) if num else '',kind=kind,attachments=attachments,links=links)
