"""User-authorized, once-per-day policy digests with a durable send ledger."""
import re
import secrets
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from threading import Lock

import httpx
from sqlalchemy import select, update, exists
from .models import (Document, Follow, Notification, Outbox, Revision, User,
                     PushSubscription, PushGrant, PushDigest, PushDigestItem, now)

CHINA = ZoneInfo('Asia/Shanghai')
_CLAIM = Lock()


def configured(settings):
    return bool(settings.wechat_push_enabled and settings.wechat_push_template_id
                and settings.wechat_app_id and settings.wechat_secret)


def status(db, user_id, settings):
    sub = db.get(PushSubscription, user_id)
    active = bool(sub and sub.enabled and sub.template_id == settings.wechat_push_template_id)
    return {'available': configured(settings), 'enabled': active, 'credits': sub.credits if active else 0,
            'template_id': settings.wechat_push_template_id if configured(settings) else '',
            'mode': 'once', 'send_time': '09:00'}


def prepare(db, user_id, settings, clock=None):
    clock = now() if clock is None else clock
    if not configured(settings): raise ValueError('push_not_available')
    if not db.scalar(select(Follow.id).where(Follow.user_id == user_id).limit(1)):
        raise ValueError('follow_required')
    grant = db.scalar(select(PushGrant).where(PushGrant.user_id == user_id, PushGrant.result == 'pending',
        PushGrant.template_id == settings.wechat_push_template_id, PushGrant.expires > clock))
    if not grant:
        grant = PushGrant(id=secrets.token_urlsafe(24), user_id=user_id,
            template_id=settings.wechat_push_template_id, expires=clock+600)
        db.add(grant); db.flush()
    return {'grant_id': grant.id, 'template_id': grant.template_id, 'expires_at': grant.expires}


def disable(db, user_id):
    sub = db.get(PushSubscription, user_id)
    if sub: sub.enabled, sub.credits, sub.updated = False, 0, now()
    for grant in db.scalars(select(PushGrant).where(PushGrant.user_id == user_id, PushGrant.result == 'pending')):
        grant.result = 'cancelled'
    for digest in db.scalars(select(PushDigest).where(PushDigest.user_id == user_id, PushDigest.state == 'queued')):
        digest.state, digest.error = 'cancelled', 'user_disabled'


def confirm(db, user_id, settings, grant_id, result, mini_state, clock=None):
    clock = now() if clock is None else clock
    grant = db.get(PushGrant, grant_id)
    if not grant or grant.user_id != user_id: raise ValueError('grant_not_found')
    if grant.result != 'pending':
        if grant.result != result: raise ValueError('grant_cancelled')
        return status(db, user_id, settings)
    if grant.expires <= clock or grant.template_id != settings.wechat_push_template_id:
        raise ValueError('grant_expired')
    if not configured(settings): raise ValueError('push_not_available')
    changed = db.execute(update(PushGrant).where(PushGrant.id == grant_id, PushGrant.result == 'pending')
                         .values(result=result)).rowcount
    if not changed: return status(db, user_id, settings)
    if result == 'accept':
        sub = db.get(PushSubscription, user_id)
        if not sub:
            sub = PushSubscription(user_id=user_id, template_id=grant.template_id, enabled=True,
                                   credits=0, since=clock, mini_state=mini_state)
            db.add(sub); db.flush()
        if not sub.enabled or sub.credits == 0 or sub.template_id != grant.template_id:
            sub.since = clock
        if sub.template_id != grant.template_id: sub.credits = 0
        sub.enabled, sub.template_id, sub.mini_state, sub.updated = True, grant.template_id, mini_state, clock
        db.execute(update(PushSubscription).where(PushSubscription.user_id == user_id)
                   .values(credits=PushSubscription.credits + 1))
        db.refresh(sub)
    else:
        disable(db, user_id)
    return status(db, user_id, settings)


def matches(rule, document, revision):
    return ((not rule.region or document.region == rule.region
             or (rule.include_national and document.region == 'CN'))
            and (not rule.topic or rule.topic == revision.topic))


def recent(revision, timestamp):
    try: published = datetime.strptime(revision.published or '', '%Y-%m-%d').date()
    except ValueError: return False
    today = datetime.fromtimestamp(timestamp, CHINA).date()
    return today - timedelta(days=7) <= published <= today


def collect_notifications(factory, settings, limit=200):
    if not configured(settings): return 0
    count = 0
    with factory.begin() as db:
        rows = list(db.scalars(select(Outbox).where(Outbox.delivered == False).order_by(Outbox.revision_id).limit(limit)))
        for event in rows:
            revision = db.get(Revision, event.revision_id)
            document = db.get(Document, revision.document_id)
            if document.status == 'ready' and revision.number == 1 and recent(revision, document.created):
                follows = db.execute(select(Follow, PushSubscription).join(PushSubscription, PushSubscription.user_id == Follow.user_id)
                    .where(PushSubscription.enabled == True, PushSubscription.template_id == settings.wechat_push_template_id,
                           PushSubscription.since <= document.created, Follow.created <= document.created)).all()
                for rule, sub in follows:
                    key = {'user_id': sub.user_id, 'revision_id': revision.id}
                    if matches(rule, document, revision) and not db.get(Notification, key):
                        db.add(Notification(**key, created=document.created)); db.flush(); count += 1
            event.delivered = True
    return count


def cutoff_for(clock):
    current = datetime.fromtimestamp(clock, CHINA)
    cutoff = current.replace(hour=9, minute=0, second=0, microsecond=0)
    if current < cutoff: cutoff -= timedelta(days=1)
    return cutoff


def digest_documents(db, digest):
    rules = list(db.scalars(select(Follow).where(Follow.user_id == digest.user_id)))
    originals = db.scalars(select(Revision).join(PushDigestItem, PushDigestItem.revision_id == Revision.id)
                          .where(PushDigestItem.digest_id == digest.id)).all()
    result = []
    for original in originals:
        document = db.get(Document, original.document_id)
        revision = db.get(Revision, document.current_revision)
        if document.status == 'ready' and any(matches(rule, document, revision) for rule in rules):
            result.append((document, revision))
    return sorted(result, key=lambda item: (item[1].published or '', item[0].id), reverse=True)


def schedule(factory, settings, clock=None):
    if not configured(settings): return 0
    clock = now() if clock is None else clock
    cutoff = cutoff_for(clock); timestamp = cutoff.timestamp(); count = 0
    with _CLAIM, factory.begin() as db:
        # A crash may have happened after WeChat accepted the message. Never resend
        # an ambiguous in-flight delivery automatically.
        db.execute(update(PushDigest).where(PushDigest.state == 'sending', PushDigest.lease_until < clock)
                   .values(state='uncertain', error='delivery_outcome_unknown'))
        for sub in db.scalars(select(PushSubscription).where(PushSubscription.enabled == True,
                PushSubscription.credits > 0, PushSubscription.template_id == settings.wechat_push_template_id)):
            if db.scalar(select(PushDigest.id).where(PushDigest.user_id == sub.user_id, PushDigest.day == cutoff.date().isoformat())):
                continue
            used = exists(select(PushDigestItem.revision_id).where(PushDigestItem.user_id == sub.user_id,
                          PushDigestItem.revision_id == Notification.revision_id))
            notices = list(db.scalars(select(Notification).where(Notification.user_id == sub.user_id,
                Notification.created >= max(sub.since, timestamp-7*86400), Notification.created <= timestamp,
                ~used).order_by(Notification.created.desc()).limit(500)))
            rules = list(db.scalars(select(Follow).where(Follow.user_id == sub.user_id)))
            selected = []
            for notice in notices:
                revision = db.get(Revision, notice.revision_id); document = db.get(Document, revision.document_id)
                current = db.get(Revision, document.current_revision)
                if document.status == 'ready' and any(matches(rule, document, current) for rule in rules): selected.append(notice)
            if not selected: continue
            digest = PushDigest(id=uuid.uuid4().hex, user_id=sub.user_id, day=cutoff.date().isoformat(), cutoff=timestamp,
                                template_id=sub.template_id, mini_state=sub.mini_state, available=clock)
            db.add(digest); db.flush()
            for notice in selected: db.add(PushDigestItem(user_id=sub.user_id, revision_id=notice.revision_id, digest_id=digest.id))
            count += 1
    return count


class SendError(Exception):
    def __init__(self, code, *, retry=False, uncertain=False, revoked=False):
        self.code, self.retry, self.uncertain, self.revoked = str(code), retry, uncertain, revoked
        super().__init__(self.code)


class WeChatSender:
    """Tokens stay in worker memory; error bodies and request URLs never enter logs."""
    def __init__(self, settings):
        self.settings, self.token, self.expires = settings, '', 0
        self.client = httpx.Client(timeout=15, trust_env=False, follow_redirects=False)

    def close(self): self.client.close()

    def access_token(self):
        if self.token and self.expires > now()+120: return self.token
        try:
            response = self.client.post('https://api.weixin.qq.com/cgi-bin/stable_token', json={
                'grant_type': 'client_credential', 'appid': self.settings.wechat_app_id,
                'secret': self.settings.wechat_secret, 'force_refresh': False})
            data = response.json()
        except (httpx.HTTPError, ValueError): raise SendError('token_unavailable', retry=True)
        if response.status_code != 200 or not data.get('access_token'):
            raise SendError('token_unavailable', retry=True)
        self.token, self.expires = data['access_token'], now()+int(data.get('expires_in', 7200))
        return self.token

    def send(self, payload):
        token = self.access_token()
        try:
            response = self.client.post('https://api.weixin.qq.com/cgi-bin/message/subscribe/send',
                                        params={'access_token': token}, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout):
            raise SendError('connect_failed', retry=True)
        except httpx.HTTPError: raise SendError('delivery_outcome_unknown', uncertain=True)
        if response.status_code != 200: raise SendError('delivery_outcome_unknown', uncertain=True)
        try: code = response.json()['errcode']
        except (ValueError, KeyError, TypeError): raise SendError('delivery_outcome_unknown', uncertain=True)
        if code == 0: return
        if code in (40001, 40014, 42001): self.token = ''; self.expires = 0
        raise SendError('wechat_' + str(code), retry=code in (-1, 40001, 40014, 42001, 45009), revoked=code == 43101)


def send_one(factory, settings, sender, clock=None):
    if not configured(settings): return False
    clock = now() if clock is None else clock
    with _CLAIM, factory.begin() as db:
        digest = db.scalar(select(PushDigest).where(PushDigest.state == 'queued', PushDigest.available <= clock)
                           .order_by(PushDigest.available).limit(1))
        if not digest: return False
        claimed = db.execute(update(PushDigest).where(PushDigest.id == digest.id, PushDigest.state == 'queued')
            .values(state='sending', attempts=PushDigest.attempts+1, lease_until=clock+120)).rowcount
        if not claimed: return False
        sub = db.get(PushSubscription, digest.user_id)
        docs = digest_documents(db, digest)
        if (not sub or not sub.enabled or sub.template_id != digest.template_id
                or digest.template_id != settings.wechat_push_template_id or not docs):
            if sub and sub.enabled and sub.template_id == digest.template_id and digest.reserved:
                sub.credits += 1
            digest.reserved = False
            digest.state, digest.error = 'cancelled', 'subscription_changed'
            return True
        if not digest.reserved:
            reserved = db.execute(update(PushSubscription).where(PushSubscription.user_id == sub.user_id,
                PushSubscription.credits > 0, PushSubscription.enabled == True).values(credits=PushSubscription.credits-1)).rowcount
            if not reserved:
                digest.state, digest.error = 'cancelled', 'no_subscription_credit'; return True
            digest.reserved = True
        did, user_id = digest.id, digest.user_id
        title = re.sub(r'\s+', '', docs[0][1].title)
        if len(title) > 20: title = title[:19]+'…'
        payload = {'touser': db.get(User, user_id).openid, 'template_id': digest.template_id,
            'page': 'pages/updates/updates?id='+did, 'miniprogram_state': digest.mini_state, 'lang': 'zh_CN',
            'data': {'thing5': {'value': title}, 'number12': {'value': str(len(docs))},
                     'date7': {'value': datetime.fromtimestamp(clock, CHINA).strftime('%Y-%m-%d %H:%M')},
                     'thing4': {'value': '关注范围有新文件，点击查看'}}}
    error = None
    try: sender.send(payload)
    except SendError as exc: error = exc
    except Exception: error = SendError('delivery_outcome_unknown', uncertain=True)
    with factory.begin() as db:
        digest = db.get(PushDigest, did)
        if digest.state != 'sending': return True
        sub = db.get(PushSubscription, user_id)
        if not error:
            digest.state, digest.sent, digest.error = 'sent', clock, ''
        elif error.uncertain:
            digest.state, digest.error = 'uncertain', error.code
        elif error.revoked:
            digest.state, digest.error = 'cancelled', error.code
            disable(db, user_id)
        elif error.retry and digest.attempts < 3 and sub and sub.enabled:
            digest.state, digest.error, digest.available = 'queued', error.code, clock+60*2**digest.attempts
        else:
            digest.state, digest.error = 'failed', error.code
            if sub and sub.enabled and sub.template_id == digest.template_id: sub.credits += 1
            digest.reserved = False
        digest.lease_until = None
    return True


def run_push_worker(factory, settings, stop):
    sender = WeChatSender(settings)
    try:
        while not stop.is_set():
            try:
                collect_notifications(factory, settings)
                schedule(factory, settings)
                worked = send_one(factory, settings, sender)
            except Exception:
                # Operational faults must not stop document collection or leak secrets.
                worked = False
                print('Policy push worker will retry after an operational error', flush=True)
            stop.wait(1 if worked else 30)
    finally: sender.close()
