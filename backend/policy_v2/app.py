"""Opt-in V2 API. It uses a separate database and never starts legacy jobs."""
import secrets
import hashlib
import time
import os
from datetime import date, datetime, timezone
import httpx

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from .db import Base, database
from .models import Audit, Document, Favorite, Follow, Notification, Revision, Session, Source, Task, TaskRepair, User
from .settings import REGIONS, TOPICS, Settings
from .sources import seed
from .source_health import cooldown_until
from .rounds import summary as round_summary, refresh_source
from .coverage import collection_status, scope_status
from .text_encoding import UTF8JSONResponse
from .summaries import summary_view
from .body_display import reading_body

settings = Settings(_env_file=os.environ.get('POLICY_AI_CONFIG_FILE'))
engine, SessionLocal = database(settings.database_url)
Base.metadata.create_all(engine)
seed(SessionLocal)
app = FastAPI(title="WeiJianwei Policy API", version="2.0.0", default_response_class=UTF8JSONResponse)


def summary_settings():
    """Reload only the private AI configuration; never switch the running API's DB."""
    path = os.environ.get('POLICY_AI_CONFIG_FILE')
    return Settings(_env_file=path) if path else settings


class ClassificationReview(BaseModel):
    topic: str = Field(max_length=100)
    reason: str = Field(min_length=5, max_length=500)


class WeChatLogin(BaseModel):
    code: str = Field(min_length=1, max_length=256)


class FollowRule(BaseModel):
    region: str = Field(default="", max_length=10)
    topic: str = Field(default="", max_length=100)
    include_national: bool = True


def admin(authorization: str | None = Header(default=None)):
    token = settings.admin_token
    if not token or not authorization or not secrets.compare_digest(authorization.removeprefix("Bearer "), token):
        raise HTTPException(401, "admin_auth_required")


def current_user(authorization: str | None = Header(default=None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(401, "login_required")
    token_hash = hashlib.sha256(authorization[7:].encode()).hexdigest()
    with SessionLocal() as db:
        session = db.get(Session, token_hash)
        if not session or session.expires <= time.time(): raise HTTPException(401, "session_expired")
        return session.user_id


@app.post("/api/v2/auth/wechat")
def wechat_login(payload: WeChatLogin):
    if not settings.wechat_app_id or not settings.wechat_secret:
        raise HTTPException(503, "wechat_login_not_configured")
    try:
        response = httpx.get("https://api.weixin.qq.com/sns/jscode2session", params={
            "appid": settings.wechat_app_id, "secret": settings.wechat_secret,
            "js_code": payload.code, "grant_type": "authorization_code"}, timeout=10)
        response.raise_for_status(); data=response.json()
    except httpx.HTTPError as exc:
        raise HTTPException(502, "wechat_login_unavailable") from exc
    openid=data.get("openid")
    if not openid or data.get("errcode"):
        raise HTTPException(401, "wechat_code_invalid")
    raw_token=secrets.token_urlsafe(32); token_hash=hashlib.sha256(raw_token.encode()).hexdigest()
    expires=time.time()+settings.session_days*86400
    with SessionLocal.begin() as db:
        user=db.scalar(select(User).where(User.openid==openid))
        if not user: user=User(openid=openid); db.add(user); db.flush()
        db.add(Session(token_hash=token_hash,user_id=user.id,expires=expires))
        return {"access_token":raw_token,"expires_at":datetime.fromtimestamp(expires,timezone.utc).isoformat()}


@app.get("/api/v2/me/favorites")
def list_favorites(user_id: int = Depends(current_user)):
    with SessionLocal() as db:
        rows=db.execute(select(Document,Revision).join(Favorite,Favorite.document_id==Document.id)
            .join(Revision,Revision.id==Document.current_revision).where(Favorite.user_id==user_id)
            .order_by(Favorite.created.desc())).all()
        return [{"id":d.id,"title":r.title,"region":d.region,"authority":r.authority,
                 "published":r.published,"type":r.kind,"topic":r.topic,"original_url":d.url}
                for d,r in rows]


@app.put("/api/v2/me/favorites/{document_id}")
def add_favorite(document_id: int, user_id: int = Depends(current_user)):
    with SessionLocal.begin() as db:
        if not db.get(Document,document_id): raise HTTPException(404,"policy_not_found")
        key={"user_id":user_id,"document_id":document_id}
        if not db.get(Favorite,key): db.add(Favorite(**key))
        return {"document_id":document_id,"favorited":True}


@app.delete("/api/v2/me/favorites/{document_id}")
def remove_favorite(document_id: int, user_id: int = Depends(current_user)):
    with SessionLocal.begin() as db:
        favorite=db.get(Favorite,{"user_id":user_id,"document_id":document_id})
        if favorite: db.delete(favorite)
        return {"document_id":document_id,"favorited":False}


@app.get("/api/v2/me/follows")
def list_follows(user_id: int = Depends(current_user)):
    with SessionLocal() as db:
        return [{"id":f.id,"region":f.region,"topic":f.topic,"include_national":f.include_national}
                for f in db.scalars(select(Follow).where(Follow.user_id==user_id).order_by(Follow.id))]


@app.post("/api/v2/me/follows")
def add_follow(rule: FollowRule, user_id: int = Depends(current_user)):
    if rule.region and rule.region not in REGIONS: raise HTTPException(422,"unknown_region")
    if rule.topic and rule.topic not in TOPICS: raise HTTPException(422,"unknown_topic")
    with SessionLocal.begin() as db:
        match=db.scalar(select(Follow).where(Follow.user_id==user_id,Follow.region==rule.region,
            Follow.topic==rule.topic,Follow.include_national==rule.include_national))
        if not match:
            match=Follow(user_id=user_id,region=rule.region,topic=rule.topic,include_national=rule.include_national)
            db.add(match);db.flush()
        return {"id":match.id,"region":match.region,"topic":match.topic,"include_national":match.include_national}


@app.delete("/api/v2/me/follows/{follow_id}")
def remove_follow(follow_id: int, user_id: int = Depends(current_user)):
    with SessionLocal.begin() as db:
        rule = db.get(Follow, follow_id)
        if not rule or rule.user_id != user_id:
            raise HTTPException(404, "follow_not_found")
        db.delete(rule)
        return {"id": follow_id, "followed": False}


@app.get("/health")
def health():
    return {"status": "ok", "recruitment_enabled": settings.recruitment_enabled,
            "revision": os.environ.get('POLICY_RELEASE_REVISION', 'development'),
            "source_sha256": os.environ.get('POLICY_SOURCE_SHA256', '')}


@app.get("/api/v2/regions")
def regions():
    return [{"code": k, "name": v} for k, v in REGIONS.items()]


@app.get("/api/v2/source-inventory")
def source_inventory():
    from .sources import inventory, source_definitions
    fields=('id','name','region','kind','url','landing_url','status','blocker','notes','scope_note','validation')
    return {"region_basis":"collection_source", "provinces":inventory(),
            "sources":[{k:s[k] for k in fields if k in s} for s in source_definitions()]}


@app.get("/api/v2/topics")
def topics():
    return TOPICS


@app.get("/api/v2/coverage")
def coverage():
    with SessionLocal() as db:
        rows = db.scalars(select(Source).order_by(Source.region, Source.name, Source.kind)).all()
        return [collection_status(db, s) for s in rows]


@app.get("/api/v2/policies")
def policies(q: str = "", region: str = "", include_national: bool = True,
             topic: str = "", content_type: str = "", published_since: date | None = None, limit: int = Query(20, ge=1, le=100), offset: int = Query(0, ge=0)):
    ai_settings = summary_settings()
    with SessionLocal() as db:
        stmt = select(Document, Revision).join(Revision, Revision.id == Document.current_revision).where(Document.status == "ready")
        if region:
            stmt = stmt.where(Document.region.in_([region, "CN"] if include_national else [region]))
        if topic: stmt = stmt.where(Revision.topic == topic)
        if content_type: stmt = stmt.where(Revision.kind == content_type)
        if published_since: stmt = stmt.where(Revision.published >= published_since.isoformat())
        if q:
            pattern = f"%{q[:100]}%"
            stmt = stmt.where(or_(Revision.title.ilike(pattern), Revision.search_text.ilike(pattern), Revision.doc_number.ilike(pattern), Revision.authority.ilike(pattern)))
        total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        source_stmt = select(Source)
        if region:
            source_stmt = source_stmt.where(Source.region.in_([region, "CN"] if include_national else [region]))
        if content_type:
            source_stmt = source_stmt.where(Source.kind == content_type)
        sources = list(db.scalars(source_stmt))
        freshness = {
            "last_success": max((s.last_success or 0 for s in sources), default=0) or None,
            "unavailable_sources": sum(bool(s.enabled and (s.last_error or cooldown_until(s) > time.time())) for s in sources),
        }
        rows = db.execute(stmt.order_by(Revision.published.desc(), Document.id.desc()).offset(offset).limit(limit)).all()
        return {"items": [{"id": d.id, "title": r.title, "region": d.region, "authority": r.authority, "original_url": d.url,
                           "published": r.published, "type": r.kind, "topic": r.topic,
                           "summary": r.summary, "summary_status": summary_view(db, r, ai_settings), "attachments": r.attachments} for d, r in rows],
                "limit": limit, "offset": offset, "total": total, "freshness": freshness,
                "scope": scope_status(db, region, content_type, total, bool(q or topic or content_type or published_since))}


@app.get("/api/v2/policies/{document_id}")
def policy_detail(document_id: int):
    with SessionLocal() as db:
        row = db.execute(select(Document, Revision).join(Revision, Revision.id == Document.current_revision)
                         .where(Document.id == document_id, Document.status == "ready")).first()
        if not row: raise HTTPException(404, "policy_not_found")
        d, r = row
        return {"id": d.id, "title": r.title, "region": d.region, "authority": r.authority, "original_url": d.url,
                "published": r.published, "document_number": r.doc_number, "type": r.kind,
                "topic": r.topic, "body": r.body, "display_body": reading_body(db, r, settings),
                "summary": r.summary, "summary_status": summary_view(db, r, summary_settings()),
                "attachments": r.attachments, "revision": r.number}


@app.get("/api/v2/admin/sources", dependencies=[Depends(admin)])
def admin_sources():
    with SessionLocal() as db:
        return [{"id": s.id, "name": s.name, "region": s.region, "kind": s.kind,
                 "url": s.url, "enabled": s.enabled, "last_success": s.last_success,
                 "last_error": s.last_error, "listing_audit": (s.checkpoint or {}).get("last_listing"),
                 "collection_run": round_summary(db,s.id)}
                for s in db.scalars(select(Source).order_by(Source.id))]


@app.put("/api/v2/admin/sources/{source_id}/enabled", dependencies=[Depends(admin)])
def source_enabled(source_id: str, enabled: bool, reason: str = Query(..., min_length=5, max_length=500)):
    with SessionLocal.begin() as db:
        source = db.get(Source, source_id)
        if not source: raise HTTPException(404, "source_not_found")
        before = source.enabled
        source.enabled = enabled
        db.add(Audit(actor="admin-token", action="source.enabled", target=source_id,
                     reason=reason, before={"enabled": before}, after={"enabled": enabled}))
        return {"id": source_id, "enabled": source.enabled}


@app.put("/api/v2/admin/revisions/{revision_id}/classification", dependencies=[Depends(admin)])
def review_classification(revision_id: int, payload: ClassificationReview):
    if payload.topic not in TOPICS and payload.topic != "":
        raise HTTPException(422, "unknown_topic")
    with SessionLocal.begin() as db:
        revision = db.get(Revision, revision_id)
        if not revision: raise HTTPException(404, "revision_not_found")
        before = {"topic": revision.topic, "status": revision.classification_status}
        revision.topic = payload.topic
        revision.human_locked = True
        revision.classification_status = "reviewed" if payload.topic else "unclassified"
        db.add(Audit(actor="admin-token", action="classification.review", target=str(revision_id),
                     reason=payload.reason, before=before,
                     after={"topic": revision.topic, "status": revision.classification_status,
                            "human_locked": True}))
        return {"revision_id": revision_id, "topic": revision.topic,
                "status": revision.classification_status, "human_locked": revision.human_locked}


@app.get("/api/v2/admin/tasks", dependencies=[Depends(admin)])
def admin_tasks(state: str = "", limit: int = Query(50, ge=1, le=200)):
    with SessionLocal() as db:
        stmt = select(Task).order_by(Task.created.desc()).limit(limit)
        if state: stmt = stmt.where(Task.state == state)
        return [{"id": task.id, "kind": task.kind, "state": task.state,
                 "attempts": task.attempts, "error": task.error,
                 "repair_cycles": (db.get(TaskRepair,task.id).cycles if db.get(TaskRepair,task.id) else 0),
                 "available": task.available,
                 "created": task.created, "finished": task.finished}
                for task in db.scalars(stmt)]


@app.post('/api/v2/admin/tasks/{task_id}/retry', dependencies=[Depends(admin)])
def retry_task(task_id: int, reason: str = Query(..., min_length=5, max_length=500)):
    with SessionLocal.begin() as db:
        task=db.scalar(select(Task).where(Task.id==task_id).with_for_update())
        if not task:raise HTTPException(404,'task_not_found')
        if task.state!='failed':raise HTTPException(409,'task_not_failed')
        before={'state':task.state,'error':task.error,'attempts':task.attempts}
        repair=db.get(TaskRepair,task.id)
        if repair:repair.cycles=0
        task.state='queued';task.attempts=0;task.finished=None;task.owner=None;task.lease_until=None
        source=db.get(Source,task.payload.get('source_id'))
        task.available=max(time.time(),cooldown_until(source) if source else 0)
        if task.kind == 'summary':
            from .models import SummaryRecord
            record = db.get(SummaryRecord, task.payload['revision_id'])
            if record and record.task_id == task.id:
                db.get(Revision, record.revision_id).summary_status = 'queued'
        db.add(Audit(actor='admin-token',action='task.retry',target=str(task.id),reason=reason,
                     before=before,after={'state':'queued','available':task.available}))
        db.flush()
        if source:refresh_source(db,source,settings)
        return {'id':task.id,'state':task.state,'available':task.available}
