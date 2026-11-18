"""Recover reading layout from the revision's immutable original HTML."""
import hashlib
import re

from .models import RawObject, Snapshot, Source
from .parsing import parse_detail
from .storage import make_store


def reading_body(db, revision, settings):
    original = revision.body or ''
    if not original or not revision.snapshot_id:
        return original
    snapshot = db.get(Snapshot, revision.snapshot_id)
    raw = db.get(RawObject, snapshot.raw_sha) if snapshot else None
    source = db.get(Source, snapshot.source_id) if snapshot else None
    if not raw or not source or raw.size > 4 * 1024 * 1024:
        return original
    try:
        data = make_store(settings).read(raw.key)
        if hashlib.sha256(data).hexdigest() != raw.sha:
            return original
        parsed = parse_detail(data, snapshot.url, {'title': revision.title,
            'published': revision.published}, source)
        readable = parsed['display_body']
        # Never replace saved wording with a changed source selector or parser
        # result. Only whitespace/layout may differ from the evidence body.
        if re.sub(r'\s+', '', readable) == re.sub(r'\s+', '', original):
            return readable
    except Exception:
        # Layout recovery is optional; unavailable/corrupt snapshots must not
        # prevent reading the saved document or expose storage diagnostics.
        pass
    return original
