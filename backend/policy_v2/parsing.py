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

def jcms_group(data, url, config):
    from .adapters import jcms_group as read_group
    return read_group(data, url, config)

def parse_list(data, url, config):
    from .adapters import read_list
    listing = read_list(data, url, config)
    return listing.items, listing.next_url

def page_url(first,n,adapter):
    if n==1:return first
    if adapter=='nhc':return first.replace('list.shtml',f'list_{n}.shtml')
    if adapter in ('trs','gd'):return first.replace('index.html',f'index_{n}.html')
    return None # JCMS pagination must use discovered links / tested source configuration.

def parse_detail(data,url,item,source):
    s=soup(data)
    def meta(name):
        el=s.find('meta',attrs={'name':re.compile('^'+name+'$',re.I)})
        return (el.get('content') or '') if el else ''
    listed=clean(item.get('title') or '')
    metadata_title=clean(meta('ArticleTitle'))
    # Several official templates retain a stale ArticleTitle from an unrelated article.
    title=listed if listed and (source.config.get('title_from_list') or (metadata_title and listed[:10] not in metadata_title)) else (metadata_title or listed)
    body_el=None
    for selector in source.config['body_selectors']:
        el=s.select_one(selector)
        if el and (len(el.get_text(strip=True))>=30 or el.select('a[href],img,iframe[src],embed[src],object[data],video,audio')):body_el=el;break
    extra_attachments=[a for selector in source.config.get('attachment_selectors',[]) for a in s.select(selector)]
    if body_el is None:
        if not extra_attachments:raise ParseError('body_selector_missing')
        body_el=soup('<div></div>').div
    embedded=[canonical(urljoin(url,e.get('src') or e.get('data') or '')) for e in body_el.select('iframe[src],embed[src],object[data]')]
    media=[]
    for element in body_el.select('video,audio,source,iframe[durl]'):
        href=element.get('durl') or element.get('src')
        if href:
            media.append({'name':element.get('name') or '音视频原文','url':canonical(urljoin(url,href)),
                          'status':'needs_transcription','media':True})
    for tag in body_el.select('script,style,iframe,form,button'):tag.decompose()
    body=clean(body_el.get_text('\n',strip=True))
    attachments=media
    for a in [*body_el.select('a[href]'),*extra_attachments]:
        href=canonical(urljoin(url,a['href']))
        if re.search(r'\.(pdf|docx?|xlsx?|wps|et|ofd|zip|rar|pptx?)(?:$|[?#])',href,re.I):
            attachments.append({'name':a.get_text(' ',strip=True) or urlsplit(href).path.rsplit('/',1)[-1],'url':href,'status':'pending'})
    for href in embedded:
        if re.search(r'\.(pdf|docx?|xlsx?|wps|ofd)(?:$|[?#])',href,re.I):
            attachments.append({'name':urlsplit(href).path.rsplit('/',1)[-1],'url':href,'status':'pending'})
    # Image-only official interpretations are retained as image attachments; OCR is explicit, not invented text.
    for a in body_el.select('img[src]'):
        if re.search(r'/fileTypeImages/|/module/jslib/icons/|/spacer\.(?:gif|png)',a['src'],re.I):continue
        attachments.append({'name':a.get('alt') or '正文图片','url':canonical(urljoin(url,a['src'])),'status':'pending','image':True})
    unique={}
    for attachment in attachments:
        target=urlsplit(attachment['url'])
        if target.scheme=='http' and target.hostname in source.config.get('upgrade_https_hosts',[]):
            attachment['url']='https:'+attachment['url'][5:];target=urlsplit(attachment['url'])
        if attachment['status']=='pending' and (target.scheme!='https' or target.hostname not in source.config.get('hosts',[urlsplit(url).hostname])):
            attachment['status']='embedded' if target.scheme=='data' else 'external_reference'
        unique[attachment['url']]=attachment
    attachments=list(unique.values())
    if len(body)<30 and not attachments:raise ParseError('body_empty')
    date_el=s.select_one(source.config['published_selector']) if source.config.get('published_selector') else None
    visible_date=date_value(date_el.get_text(' ',strip=True)) if date_el else None
    published=(visible_date or item.get('published')) if source.config.get('published_from_list') else (visible_date or date_value(meta('PubDate')) or item.get('published'))
    authority=clean(meta('ContentSource'))
    if authority in ('本站原创','本站','其他'):authority=''  # Collection site is not necessarily the issuer.
    num=re.search(r'[\u4e00-\u9fff]{1,12}(?:\([^)]{1,10}\))?[〔\[【](?:19|20)\d{2}[〕\]】]\s*\d+\s*号',body)
    excluded=any(w in title for w in ['征求意见','公开征集','招聘','拟聘','会议召开','召开会议'])
    kind='excluded' if excluded else source.kind
    links=[{'url':canonical(urljoin(url,a['href'])),'text':a.get_text(' ',strip=True)} for a in body_el.select('a[href]') if any(w in a.get_text() for w in ['解读','政策原文','相关文件'])]
    return dict(title=title,body=body,authority=authority,published=published,doc_number=num.group(0) if num else '',kind=kind,attachments=attachments,links=links)
