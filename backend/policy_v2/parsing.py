import re
import unicodedata
from collections import Counter
from datetime import date
from urllib.parse import urljoin,urlsplit,urlunsplit,parse_qs
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

def jcms_group(data,url,config):
    """Read the embedded JCMS group or its public XML response, never execute JS.

    Some endpoints return the entire dataset despite advertising another group.
    Actual record counts, before host/type filtering, decide whether to continue.
    """
    text=data.decode('utf-8',errors='replace')
    store=re.search(r'<datastore>(.*?)</datastore>',text,re.S)
    if not store:raise ParseError('jcms_datastore_missing')
    payload=store.group(1)
    fragments=re.findall(r'<record>\s*<!\[CDATA\[(.*?)\]\]>\s*</record>',payload,re.S)
    total=re.search(r'<totalrecord>(\d+)</totalrecord>',payload)
    if not total:
        # Ignore the separate search-form initializer's placeholder totalRecord:1000.
        initializers=re.findall(r'\.jpage\(\{(.*?)\}\);',text,re.S)
        init=next((i for i in initializers if 'dataStore:' in i), '')
        total=re.search(r'\btotalRecord\s*:\s*(\d+)',init)
    if not total:raise ParseError('jcms_total_missing')
    total=int(total.group(1))
    if len(fragments)>total or (total and not fragments):raise ParseError('jcms_record_count_mismatch')
    origins=Counter();eligible=0;outside=0;non_document=0;non_matching=0
    for fragment in fragments:
        row=soup(fragment);a=row.select_one('a[href]')
        if not a or not date_value(row.get_text(' ',strip=True)):
            raise ParseError('jcms_record_malformed')
        target=canonical(urljoin(url,a['href']));host=urlsplit(target).hostname or ''
        origins[host]+=1
        title=clean(a.get('title') or a.get_text(' ',strip=True))
        if host not in config.get('list_hosts',config['hosts']):outside+=1
        elif len(title)<6 or not re.search(r'\.(?:s?html?|shtm)(?:\?|$)',target,re.I):non_document+=1
        elif config.get('include_title_pattern') and not re.search(config['include_title_pattern'],title):non_matching+=1
        else:eligible+=1
    next_url=None
    if len(fragments)<total:
        nextgroup=re.search(r'<nextgroup>\s*<!\[CDATA\[(.*?)\]\]>\s*</nextgroup>',payload,re.S)
        a=soup(nextgroup.group(1)).select_one('a[href]') if nextgroup else None
        if not a:raise ParseError('jcms_next_group_missing')
        next_url=canonical(urljoin(url,a['href']));target=urlsplit(next_url)
        if (target.scheme!='https' or target.hostname!=urlsplit(url).hostname or target.username or target.password
                or target.port not in (None,443) or target.path!='/module/web/jpage/dataproxy.jsp'
                or parse_qs(target.query).get('columnid')!=[str(config['jcms_column_id'])] or next_url==url):
            raise ParseError('jcms_next_group_not_allowed')
    return fragments,next_url,{'total_records':total,'returned_records':len(fragments),
        'complete_listing':len(fragments)==total,'link_origins':dict(origins),'eligible_records':eligible,
        'filtered_external':outside,'filtered_non_document':non_document,'filtered_content_type':non_matching}

def parse_list(data,url,config):
    jcms=config.get('adapter')=='jcms'
    group_next=None
    if jcms:
        fragments,group_next,_=jcms_group(data,url,config)
        s=soup(''.join(fragments))
    else:
        s=soup(data)
    list_hosts=config.get('list_hosts',config['hosts'])
    # JCMS servers may embed item HTML in script text / XML records rather than live DOM.
    for fragment in ([] if jcms else re.findall(r'<!\[CDATA\[(.*?)\]\]>',data.decode('utf-8',errors='replace'),re.S)):
        s.append(soup(fragment))
    rows=s.select(config['list_selector']);items=[];seen=set()
    for row in rows:
        a=row.select_one('a[href]')
        if not a:continue
        target=canonical(urljoin(url,a['href']));title=clean(a.get('title') or a.get_text(' ',strip=True))
        if len(title)<6 or target in seen or not re.search(r'\.(?:s?html?|shtm)(?:\?|$)',target,re.I):continue
        if urlsplit(target).hostname not in list_hosts:continue
        published=date_value(row.get_text(' ',strip=True))
        if not published:continue # Menu links are not list items; never fabricate publication dates.
        seen.add(target);items.append({'url':target,'title':title,'published':published})
    if not items and not jcms:raise ParseError('list_empty_or_selector_changed')
    next_url=group_next
    for a in s.select('a[href]'):
        if a.get_text(strip=True) in ('下一页','下页','>','下一页 >'):
            candidate=canonical(urljoin(url,a['href']))
            if candidate!=url and urlsplit(candidate).hostname in list_hosts:next_url=candidate;break
    if not next_url and config.get('pagination') in ('hunan-trs', 'nhc-static'):
        # Read the site's actual page count/current page; never execute its script.
        element,prefix,suffix=('paging','index','html') if config['pagination']=='hunan-trs' else ('page_div','list','shtml')
        paging=re.search(rf"createPageHTML\(\s*'{element}'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'{prefix}'\s*,\s*'{suffix}'", data.decode('utf-8',errors='replace'))
        if paging:
            total,current=map(int,paging.groups())
            if 1 <= current < total:
                next_url=canonical(urljoin(url,f'{prefix}_{current+1}.{suffix}'))
    if config.get('include_title_pattern'):
        items=[item for item in items if re.search(config['include_title_pattern'],item['title'])]
    return items,next_url

def page_url(first,n,adapter):
    if n==1:return first
    if adapter=='nhc':return first.replace('list.shtml',f'list_{n}.shtml')
    if adapter in ('trs','gd'):return first.replace('index.html',f'index_{n}.html')
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
    date_el=s.select_one(source.config['published_selector']) if source.config.get('published_selector') else None
    visible_date=date_value(date_el.get_text(' ',strip=True)) if date_el else None
    published=(visible_date or item.get('published')) if source.config.get('published_from_list') else (visible_date or date_value(meta('PubDate')) or item.get('published'))
    authority=clean(meta('ContentSource') or source.name)
    num=re.search(r'[\u4e00-\u9fff]{1,12}(?:\([^)]{1,10}\))?[〔\[【](?:19|20)\d{2}[〕\]】]\s*\d+\s*号',body)
    excluded=any(w in title for w in ['征求意见','公开征集','招聘','拟聘','会议召开','召开会议'])
    kind='excluded' if excluded else source.kind
    links=[{'url':canonical(urljoin(url,a['href'])),'text':a.get_text(' ',strip=True)} for a in body_el.select('a[href]') if any(w in a.get_text() for w in ['解读','政策原文','相关文件'])]
    return dict(title=title,body=body,authority=authority,published=published,doc_number=num.group(0) if num else '',kind=kind,attachments=attachments,links=links)
