"""Behavior tests for consent, live intake, daily digests and uncertain delivery."""
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import hashlib
import uuid

import httpx
import pytest
from sqlalchemy import select, func
from policy_v2.db import Base, database
from policy_v2.models import (User, Source, Follow, Document, Revision, Outbox,
    Notification, PushSubscription, PushDigest, PushDigestItem, Session)
from policy_v2.settings import Settings
from policy_v2 import push


def stamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=push.CHINA).timestamp()


BEFORE = stamp('2026-11-17T10:00:00')
NEW = stamp('2026-11-17T11:00:00')
SEND = stamp('2026-11-18T09:00:00')


@pytest.fixture
def env(tmp_path):
    engine, factory = database('sqlite:///' + str(tmp_path / 'push.db'))
    Base.metadata.create_all(engine)
    settings = Settings(wechat_app_id='test-app', wechat_secret='test-secret',
                        wechat_push_enabled=True, wechat_push_template_id='test-template')
    with factory.begin() as db:
        db.add_all([User(id=1, openid='test-user'), User(id=2, openid='other-user'),
            Source(id='test', name='Test', region='CN', kind='policy', url='https://example.com')])
        db.flush()
        db.add(Follow(user_id=1, region='GD', topic='医疗服务与质量安全', include_national=True, created=BEFORE))
    yield factory, settings
    engine.dispose()


def accept(env, clock=BEFORE, user=1):
    factory, settings = env
    with factory.begin() as db:
        grant = push.prepare(db, user, settings, clock)
        return push.confirm(db, user, settings, grant['grant_id'], 'accept', 'trial', clock)


def document(env, *, region='CN', topic='医疗服务与质量安全', created=NEW,
             published='2026-11-17', number=1, state='ready'):
    factory, _ = env
    with factory.begin() as db:
        doc = Document(source_id='test', url='https://example.com/'+uuid.uuid4().hex,
                       region=region, status=state, created=created)
        db.add(doc); db.flush()
        rev = Revision(document_id=doc.id, number=number, fingerprint=uuid.uuid4().hex,
                       title='关于进一步加强医疗质量管理和安全保障的政策通知',
                       body='政策正文', kind='policy', topic=topic, published=published)
        db.add(rev); db.flush(); doc.current_revision=rev.id
        db.add(Outbox(revision_id=rev.id))
        return doc.id, rev.id


def queue(env):
    accept(env); document(env)
    assert push.collect_notifications(*env) == 1
    assert push.schedule(*env, SEND) == 1


class Sender:
    def __init__(self, error=None): self.calls, self.error = [], error
    def send(self, payload):
        self.calls.append(payload)
        if self.error: raise self.error


def test_consent_is_account_scoped_expiring_and_idempotent(env):
    factory, settings = env
    with factory.begin() as db:
        grant=push.prepare(db,1,settings,BEFORE)
        assert push.prepare(db,1,settings,BEFORE) == grant
        with pytest.raises(ValueError, match='grant_not_found'):
            push.confirm(db,2,settings,grant['grant_id'],'accept','formal',BEFORE)
        with pytest.raises(ValueError, match='grant_expired'):
            push.confirm(db,1,settings,grant['grant_id'],'accept','formal',BEFORE+601)
        first=push.confirm(db,1,settings,grant['grant_id'],'accept','trial',BEFORE)
        again=push.confirm(db,1,settings,grant['grant_id'],'accept','trial',BEFORE)
        assert first['credits'] == again['credits'] == 1
    assert accept(env)['credits'] == 2
    with factory.begin() as db:
        grant=push.prepare(db,1,settings,BEFORE)
        push.disable(db,1)
        with pytest.raises(ValueError,match='grant_cancelled'):
            push.confirm(db,1,settings,grant['grant_id'],'accept','trial',BEFORE)
        assert push.status(db,1,settings)['credits'] == 0


def test_only_new_matching_documents_after_follow_and_consent_are_collected(env):
    accept(env)
    factory, _ = env
    with factory.begin() as db:
        db.add(Follow(user_id=1,region='CN',topic='',created=BEFORE)) # overlapping rule
        db.add(Follow(user_id=2,region='CN',topic='',created=BEFORE)) # no consent
    document(env); document(env,region='GD')
    document(env,region='BJ'); document(env,region='GD',topic='other')
    document(env,created=BEFORE-1); document(env,published='2020-01-01')
    document(env,published='2026-12-01'); document(env,published=None)
    document(env,number=2); document(env,state='excluded')
    assert push.collect_notifications(*env) == 2
    assert push.collect_notifications(*env) == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(Notification)) == 2
        assert db.scalar(select(func.count()).select_from(Outbox).where(Outbox.delivered == False)) == 0


def test_daily_digest_boundary_credit_payload_and_no_duplicate_send(env):
    factory, settings=env
    accept(env); document(env); document(env,region='GD')
    push.collect_notifications(*env)
    assert push.schedule(*env, SEND-1) == 0
    assert push.schedule(*env, SEND) == 1
    assert push.schedule(*env, SEND+1) == 0
    sender=Sender()
    assert push.send_one(*env,sender,SEND)
    assert not push.send_one(*env,sender,SEND+1)
    payload=sender.calls[0]
    assert payload['touser']=='test-user' and payload['miniprogram_state']=='trial'
    assert len(payload['data']['thing5']['value']) <= 20
    assert payload['data']['number12']['value']=='2'
    assert payload['data']['date7']['value']=='2026-11-18 09:00'
    with factory() as db:
        digest=db.scalar(select(PushDigest))
        assert digest.state=='sent' and digest.attempts==1
        assert payload['page']=='pages/updates/updates?id='+digest.id
        assert db.get(PushSubscription,1).credits==0
    accept(env, SEND+1)
    assert push.schedule(*env,SEND+86400)==0


@pytest.mark.parametrize('error,state,credits', [
    (push.SendError('connection',retry=True),'queued',0),
    (push.SendError('unknown',uncertain=True),'uncertain',0),
    (push.SendError('bad_template'),'failed',1),
    (push.SendError('wechat_43101',revoked=True),'cancelled',0)])
def test_delivery_failure_classification(env,error,state,credits):
    queue(env); factory,_=env; sender=Sender(error)
    assert push.send_one(*env,sender,SEND)
    with factory() as db:
        assert db.scalar(select(PushDigest)).state==state
        assert db.get(PushSubscription,1).credits==credits
        if error.revoked: assert not db.get(PushSubscription,1).enabled
    if state!='queued':
        assert not push.send_one(*env,sender,SEND+600)
        assert push.schedule(*env,SEND+86400)==0


def test_bounded_retries_reserve_only_one_credit(env):
    queue(env); factory,_=env; sender=Sender(push.SendError('connect',retry=True))
    for clock in (SEND,SEND+120,SEND+360): assert push.send_one(*env,sender,clock)
    assert not push.send_one(*env,sender,SEND+900)
    with factory() as db:
        digest=db.scalar(select(PushDigest))
        assert digest.state=='failed' and digest.attempts==3
        assert db.get(PushSubscription,1).credits==1


def test_crash_during_send_never_resends_and_concurrent_claim_is_unique(env):
    queue(env); factory,_=env; sender=Sender()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda _:push.send_one(*env,sender,SEND),range(2)))
    assert sorted(results)==[False,True] and len(sender.calls)==1
    with factory.begin() as db:
        digest=db.scalar(select(PushDigest)); digest.state='sending'; digest.lease_until=SEND+120
    push.schedule(*env,SEND+121)
    with factory() as db: assert db.scalar(select(PushDigest)).state=='uncertain'
    assert not push.send_one(*env,sender,SEND+300)


def test_unfollow_before_delivery_cancels_without_consuming_credit(env):
    queue(env); factory,_=env
    with factory.begin() as db:
        for rule in db.scalars(select(Follow)): db.delete(rule)
    sender=Sender(); assert push.send_one(*env,sender,SEND)
    assert sender.calls==[]
    with factory() as db:
        assert db.scalar(select(PushDigest)).state=='cancelled'
        assert db.get(PushSubscription,1).credits==1


def test_live_ingestion_creates_event_but_history_and_edits_do_not(env):
    from policy_v2.ingestion import persist_detail
    factory,_=env
    parsed=dict(title='政策通知', body='正文',published='2026-11-17',authority='委',
                doc_number='',kind='policy',attachments=[])
    stored=dict(sha='a'*64,size=1,mime='text/html',key='test')
    with factory.begin() as db:
        source=db.get(Source,'test')
        persist_detail(db,source,parsed,stored,'https://example.com/a',method='http')
        persist_detail(db,source,parsed,stored,'https://example.com/a',method='http')
        persist_detail(db,source,{**parsed,'body':'修改正文'},stored,'https://example.com/a',method='http')
        persist_detail(db,source,parsed,stored,'https://example.com/b',method='verified-cache')
        assert db.scalar(select(func.count()).select_from(Outbox))==1


def test_sender_classifies_timeout_rejection_and_refreshes_token(env):
    _,settings=env
    sender=push.WeChatSender(settings)
    outcomes=[httpx.ReadTimeout('sensitive-request-url'), {'errcode':40001}, {'errcode':0}]
    token_requests=[]
    def handler(request):
        if request.url.path.endswith('stable_token'):
            token_requests.append(True)
            return httpx.Response(200,json={'access_token':'private-token','expires_in':7200})
        outcome=outcomes.pop(0)
        if isinstance(outcome,Exception): raise outcome
        return httpx.Response(200,json=outcome)
    sender.client.close(); sender.client=httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(push.SendError) as unknown: sender.send({})
    assert unknown.value.uncertain and 'sensitive' not in str(unknown.value)
    with pytest.raises(push.SendError) as expired: sender.send({})
    assert expired.value.retry and sender.token==''
    sender.send({}); assert len(token_requests)==2
    sender.close()


def test_push_api_requires_login_and_hides_other_accounts(env,monkeypatch):
    from fastapi.testclient import TestClient
    from policy_v2 import app as application
    factory,settings=env
    monkeypatch.setattr(application,'SessionLocal',factory)
    monkeypatch.setattr(application,'summary_settings',lambda:settings)
    with factory.begin() as db:
        for uid in (1,2):
            db.add(Session(token_hash=hashlib.sha256(str(uid).encode()).hexdigest(),user_id=uid,expires=1e12))
    headers={'Authorization':'Bearer 1'}
    with TestClient(application.app) as client:
        assert client.get('/api/v2/me/push').status_code==401
        grant=client.post('/api/v2/me/push/prepare',headers=headers).json()
        payload=dict(grant_id=grant['grant_id'],result='accept',mini_state='trial')
        assert client.post('/api/v2/me/push/confirm',headers={'Authorization':'Bearer 2'},json=payload).status_code==409
        assert client.post('/api/v2/me/push/confirm',headers=headers,json=payload).json()['credits']==1
        assert client.post('/api/v2/me/push/confirm',headers=headers,json=payload).json()['credits']==1
        with factory.begin() as db: db.get(PushSubscription,1).since=BEFORE
        document(env); push.collect_notifications(*env); push.schedule(*env,SEND)
        with factory() as db: did=db.scalar(select(PushDigest.id))
        assert client.get('/api/v2/me/updates/'+did,headers=headers).json()['total']==1
        assert client.get('/api/v2/me/updates/'+did,headers={'Authorization':'Bearer 2'}).status_code==404
        assert client.delete('/api/v2/me/push',headers=headers).json()['enabled'] is False


def test_simultaneous_identical_source_bytes_do_not_fail_collection(env):
    from threading import Barrier
    from policy_v2.ingestion import persist_raw
    from policy_v2.models import RawObject
    factory,_=env; barrier=Barrier(2)
    stored=dict(sha='b'*64,size=3,mime='text/html',key='raw/shared')
    def persist(index):
        with factory.begin() as db:
            assert db.get(RawObject,stored['sha']) is None
            barrier.wait(timeout=5)
            persist_raw(db,stored)
    with ThreadPoolExecutor(max_workers=2) as pool: list(pool.map(persist,range(2)))
    with factory() as db: assert db.scalar(select(func.count()).select_from(RawObject))==1
