"""Persist origin cooldowns so restarts and sibling columns respect Retry-After."""
import time
from urllib.parse import urlsplit
from sqlalchemy import select
from .db import transaction
from .models import Source


def cooldown_until(source):
    return float((source.checkpoint or {}).get('cooldown_until', 0))


def record_failure(factory, source_id, error, settings, now=None):
    now = time.time() if now is None else now
    with transaction(factory) as db:
        source = db.get(Source, source_id)
        if source is None:
            return now
        host = urlsplit(source.url).hostname
        siblings = [s for s in db.scalars(select(Source)) if urlsplit(s.url).hostname == host]
        failures = max(int((s.checkpoint or {}).get('consecutive_failures', 0)) for s in siblings) + 1
        delay = min(3600, settings.source_cooldown_seconds * 2 ** min(failures - 1, 5))
        delay = max(delay, getattr(error, 'retry_after', None) or 0)
        until = max(now + delay, *(cooldown_until(s) for s in siblings))
        for sibling in siblings:
            sibling.checkpoint = {**(sibling.checkpoint or {}), 'consecutive_failures': failures, 'cooldown_until': until}
        source.last_error = f'{type(error).__name__}:{error}'[:500]
        return until


def record_success(factory, source_id, now=None):
    now = time.time() if now is None else now
    with transaction(factory) as db:
        source = db.get(Source, source_id)
        if source is None:
            return
        host = urlsplit(source.url).hostname
        for sibling in db.scalars(select(Source)):
            if urlsplit(sibling.url).hostname == host:
                sibling.checkpoint = {**(sibling.checkpoint or {}), 'consecutive_failures': 0, 'cooldown_until': 0}
        source.last_success = now
        source.last_error = ''
