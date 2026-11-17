"""Site-family adapters return content and a filter audit through one interface."""
import re
from collections import Counter
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, parse_qs
from .parsing import ParseError, canonical, date_value, soup, clean

@dataclass
class Listing:
    items: list
    next_url: str | None
    audit: dict

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



def resolve(url, href, config):
    target = canonical(urljoin(url, href))
    # Only explicitly verified HTTPS equivalents may replace old HTTP links.
    if urlsplit(target).scheme == 'http' and urlsplit(target).hostname in config.get('upgrade_https_hosts', []):
        target = 'https:' + target[5:]
    return target


def pagination(text, dom, url, config):
    allowed = config.get('list_hosts', config['hosts'])
    if config.get('browser_total_selector'):
        marker=dom.select_one(config['browser_total_selector'])
        if marker is None:raise ParseError('pagination_marker_missing')
        total=int(marker.get_text(strip=True))
        cursor=re.fullmatch(r'collector-page=(\d+)',urlsplit(url).fragment)
        current=int(cursor[1]) if cursor else 1
        return canonical(url)+'#collector-page='+str(current+1) if current<total else None
    if config.get('browser_next'):
        el=dom.select_one(config['browser_next'])
        if el:
            value=el.get(config.get('browser_page_attribute','data-page'),'')
            if not value and config.get('browser_page_from_text'):value=el.get_text(strip=True)
            if value.isdigit():
                return canonical(url)+'#collector-page='+value
        return None
    if config.get('next_attribute'):
        el=dom.select_one(config['next_selector'])
        value=el.get(config['next_attribute'],'') if el else ''
        if value and not re.search(r'\[[A-Z_]+\]',value):
            candidate=resolve(url,value,config)
            if candidate!=url and urlsplit(candidate).hostname in allowed:return candidate
        return None
    for a in dom.select(config.get('next_selector', 'a[href]')):
        if config.get('next_selector') or a.get_text(strip=True) in ('下一页','下页','>','下一页 >'):
            candidate = resolve(url, a.get('href',''), config)
            u = urlsplit(candidate)
            if candidate != url and u.scheme == 'https' and u.hostname in allowed:
                return candidate
    mode = config.get('pagination')
    if mode in ('hunan-trs','nhc-static'):
        element,prefix,suffix=('paging','index','html') if mode=='hunan-trs' else ('page_div','list','shtml')
        m=re.search(rf"createPageHTML\(\s*'{element}'\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*'{prefix}'\s*,\s*'{suffix}'",text)
        if m:
            total,current=map(int,m.groups())
            if 1 <= current < total:return canonical(urljoin(url,f'{prefix}_{current+1}.{suffix}'))
    if isinstance(mode, dict):
        if mode.get('mode')=='count_attribute':
            marker=dom.select_one(mode['selector'])
            if marker is None:raise ParseError('pagination_marker_missing')
            total=int(marker[mode['total_attribute']]);size=int(marker[mode['size_attribute']])
            current_match=re.search(mode['current_url_pattern'],urlsplit(url).path)
            current=int(current_match[1]) if current_match else 0
            if size<=0:raise ParseError('invalid_page_size')
            if (current+1)*size<total:return canonical(urljoin(url,mode['template'].format(page=current+1)))
            return None
        # Patterns and output templates are reviewed registry data, never remote code.
        m = re.search(mode['pattern'], text, re.S)
        if not m:raise ParseError('pagination_marker_missing')
        values=m.groupdict();total=int(values['total']);current=int(values.get('current') or 0)
        first=mode.get('first_index',0)
        if current+1 < total+first:
            return canonical(urljoin(url,mode['template'].format(page=current+1)))
    return None


def read_list(data, url, config):
    adapter = config.get('adapter','html')
    if adapter not in ('html','trs','gd','nhc','jcms'):
        raise ParseError('unknown_adapter:'+adapter)
    group_next=None; group_audit=None
    text=data.decode('utf-8',errors='replace')
    if adapter=='jcms':
        fragments,group_next,group_audit=jcms_group(data,url,config)
        dom=soup(''.join(fragments))
    else:
        dom=soup(data)
        for fragment in re.findall(r'<!\[CDATA\[(.*?)\]\]>',text,re.S):dom.append(soup(fragment))
    rows=dom.select(config['list_selector']);items=[];seen=set();counts=Counter();origins=Counter()
    hosts=config.get('list_hosts',config['hosts'])
    pattern=config.get('detail_url_pattern',r'\.(?:s?html?|shtm)(?:\?|$)')
    for row in rows:
        anchors=row.select(config.get('link_selector','a[href]'))
        a=next((a for a in anchors if len(clean(a.get('title') or a.get_text(' ',strip=True)))>=6),None)
        if not a:counts['filtered_non_document']+=1;continue
        target=resolve(url,a['href'],config)
        title_el=a.select_one(config['title_selector']) if config.get('title_selector') else None
        title=clean(a.get('title') or (title_el.get('title') or title_el.get_text(' ',strip=True) if title_el else a.get_text(' ',strip=True)))
        date_el=row.select_one(config['list_date_selector']) if config.get('list_date_selector') else row
        published=date_value(date_el.get_text(' ',strip=True)) if date_el else None
        if (not published and not config.get('date_from_detail')) or not re.search(pattern,target,re.I):counts['filtered_non_document']+=1;continue
        origins[urlsplit(target).hostname or '']+=1
        counts['dated_records']+=1
        if urlsplit(target).hostname not in hosts:counts['filtered_external']+=1;continue
        if target in seen:counts['filtered_duplicate']+=1;continue
        seen.add(target)
        if config.get('include_title_pattern') and not re.search(config['include_title_pattern'],title):
            counts['filtered_content_type']+=1;continue
        if config.get('exclude_title_pattern') and re.search(config['exclude_title_pattern'],title):
            counts['filtered_content_type']+=1;continue
        items.append(dict(url=target,title=title,published=published))
    if not counts['dated_records'] and group_audit is None:raise ParseError('list_empty_or_selector_changed')
    next_url=group_next if group_audit is not None else pagination(text,dom,url,config)
    audit={**dict(counts),'returned_records':len(rows),'eligible_records':len(items),'link_origins':dict(origins),
           'pagination_detected':bool(next_url),'complete_listing':None}
    if group_audit is not None:audit.update(group_audit)
    return Listing(items,next_url,audit)
