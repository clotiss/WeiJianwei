"""Separate registered coverage, persisted content, historical sweeps and current health."""
import time
from sqlalchemy import func, select
from .models import CollectionRun, Document, Source
from .rounds import summary
from .source_health import cooldown_until
from .sources import source_definitions


def collection_status(db, source):
    first = db.scalar(select(CollectionRun).where(CollectionRun.source_id == source.id).order_by(CollectionRun.id).limit(1))
    documents = db.scalar(select(func.count()).select_from(Document).where(Document.source_id == source.id, Document.status == 'ready')) or 0
    history = 'complete' if first and first.state == 'succeeded' else (
        'blocked' if first and (first.error or first.stop_reason) else 'running' if first else 'not_started')
    return {'id': source.id, 'name': source.name, 'region': source.region, 'kind': source.kind,
        'enabled': source.enabled, 'documents': documents, 'history_state': history,
        'history_pages': first.pages_read if first else 0,
        'history_listing_complete': bool(first and first.listing_complete),
        'last_success': source.last_success, 'cooldown_until': cooldown_until(source),
        'collection_run': summary(db, source.id),
        'status': 'paused' if not source.enabled else 'cooling_down' if cooldown_until(source) > time.time()
            else 'error' if source.last_error else 'active'}


def scope_status(db, region, content_type, total, filtered):
    # Focus on the requested province: national fallback must not hide a blocked province.
    definitions = [s for s in source_definitions() if (not region or s['region'] == region)
                   and (not content_type or s['kind'] == content_type)]
    query = select(Source)
    if region:
        query = query.where(Source.region == region)
    if content_type:
        query = query.where(Source.kind == content_type)
    rows = [collection_status(db, s) for s in db.scalars(query)]
    available = sum(r['documents'] for r in rows)
    enabled = sum(r['enabled'] for r in rows)
    incomplete = sum(r['history_state'] != 'complete' for r in rows)
    failures = sum(r['status'] in ('error', 'cooling_down') or r['history_state'] == 'blocked' for r in rows)
    connected = bool(rows)
    state = 'ready'
    if not connected:
        state = 'not_connected'
    elif not total and filtered and available:
        state = 'no_matches'
    elif failures:
        state = 'unavailable'
    elif not enabled and not available:
        state = 'paused'
    elif incomplete and enabled:
        state = 'backfilling'
    elif not total:
        state = 'empty'
    messages = {
        'not_connected': ('该地区来源尚未接通', '官网访问问题仍在排查，接通后会补录内容。'),
        'no_matches': ('没有找到匹配的政策', '可清除类型、主题、日期或关键词筛选后重试。'),
        'unavailable': ('采集暂时受阻', '已收录内容仍可阅读，失败任务将按计划重试。'),
        'paused': ('该来源尚未开始采集', '已登记来源，启用后会补录内容。'),
        'backfilling': ('历史内容正在补录', '已收录内容可先阅读，更多内容会陆续加入。'),
        'empty': ('当前来源暂无已收录文件', '这不代表官网未发布内容，可查看来源与更新。'),
        'ready': ('', ''),
    }
    title, message = messages[state]
    return {'region': region, 'state': state, 'connected': connected, 'available_documents': available,
        'registered_sources': len(definitions), 'enabled_sources': enabled, 'history_pending_sources': incomplete,
        'unavailable_sources': failures, 'title': title, 'message': message}
