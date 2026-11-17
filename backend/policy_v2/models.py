from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, JSON, ForeignKey, UniqueConstraint, Index, Float
from .db import Base

def now(): return datetime.now(timezone.utc).timestamp()
class DomainState(Base):
    __tablename__='v2_domains'
    host=Column(String(255),primary_key=True)
    owner=Column(String(100))
    lease_until=Column(Float,nullable=False,default=0)
    next_allowed=Column(Float,nullable=False,default=0)
    cooldown_until=Column(Float,nullable=False,default=0)

class Source(Base):
    __tablename__='v2_sources'
    id=Column(String(40),primary_key=True)
    name=Column(String(100),nullable=False)
    region=Column(String(10),nullable=False)
    kind=Column(String(30),nullable=False)
    url=Column(Text,nullable=False)
    config=Column(JSON,nullable=False,default=dict)
    enabled=Column(Boolean,nullable=False,default=False)
    interval_seconds=Column(Integer,nullable=False,default=21600)
    last_scheduled=Column(Float,nullable=False,default=0)
    last_success=Column(Float)
    last_error=Column(Text,nullable=False,default='')
    checkpoint=Column(JSON,nullable=False,default=dict)
class RawObject(Base):
    __tablename__='v2_raw_objects'
    sha=Column(String(64),primary_key=True)
    size=Column(Integer,nullable=False)
    mime=Column(String(150),nullable=False)
    key=Column(Text,nullable=False)
    created=Column(Float,nullable=False,default=now)
class Snapshot(Base):
    __tablename__='v2_snapshots'
    id=Column(Integer,primary_key=True)
    source_id=Column(String(40),ForeignKey('v2_sources.id'),nullable=False)
    url=Column(Text,nullable=False)
    raw_sha=Column(String(64),ForeignKey('v2_raw_objects.sha'),nullable=False)
    fetched=Column(Float,nullable=False,default=now)
    method=Column(String(30),nullable=False,default='http')
class Document(Base):
    __tablename__='v2_documents'
    id=Column(Integer,primary_key=True)
    legacy_id=Column(Integer,unique=True)
    source_id=Column(String(40),ForeignKey('v2_sources.id'),nullable=False)
    url=Column(Text,nullable=False,unique=True)
    region=Column(String(10),nullable=False,index=True)
    current_revision=Column(Integer)
    status=Column(String(30),nullable=False,default='pending',index=True)
    created=Column(Float,nullable=False,default=now,index=True)
    updated=Column(Float,nullable=False,default=now)
class Revision(Base):
    __tablename__='v2_revisions'
    id=Column(Integer,primary_key=True)
    document_id=Column(Integer,ForeignKey('v2_documents.id'),nullable=False,index=True)
    number=Column(Integer,nullable=False)
    fingerprint=Column(String(64),nullable=False)
    snapshot_id=Column(Integer,ForeignKey('v2_snapshots.id'))
    title=Column(Text,nullable=False)
    body=Column(Text,nullable=False,default='')
    authority=Column(Text,nullable=False,default='')
    published=Column(String(10),index=True)
    doc_number=Column(String(150),nullable=False,default='')
    kind=Column(String(30),nullable=False,index=True)
    topic=Column(String(100),nullable=False,default='',index=True)
    classification_status=Column(String(30),nullable=False,default='pending')
    classification_evidence=Column(JSON,nullable=False,default=list)
    human_locked=Column(Boolean,nullable=False,default=False)
    summary=Column(JSON,nullable=False,default=list)
    summary_status=Column(String(30),nullable=False,default='pending')
    attachments=Column(JSON,nullable=False,default=list)
    search_text=Column(Text,nullable=False,default='')
    search_tokens=Column(Text,nullable=False,default='')
    parser_version=Column(String(50),nullable=False,default='html-v1')
    classifier_version=Column(String(100),nullable=False,default='')
    created=Column(Float,nullable=False,default=now)
    __table_args__=(UniqueConstraint('document_id','number'),)
class Relation(Base):
    __tablename__='v2_relations'
    id=Column(Integer,primary_key=True)
    from_id=Column(Integer,ForeignKey('v2_documents.id'),nullable=False)
    to_id=Column(Integer,ForeignKey('v2_documents.id'),nullable=False)
    kind=Column(String(30),nullable=False)
    evidence=Column(Text,nullable=False)
    reviewed=Column(Boolean,nullable=False,default=False)
    __table_args__=(UniqueConstraint('from_id','to_id','kind'),)
class Task(Base):
    __tablename__='v2_tasks'
    id=Column(Integer,primary_key=True)
    kind=Column(String(30),nullable=False)
    key=Column(String(200),unique=True,nullable=False)
    payload=Column(JSON,nullable=False)
    state=Column(String(30),nullable=False,default='queued',index=True)
    priority=Column(Integer,nullable=False,default=10)
    attempts=Column(Integer,nullable=False,default=0)
    available=Column(Float,nullable=False,default=now)
    lease_until=Column(Float)
    owner=Column(String(100))
    error=Column(Text,nullable=False,default='')
    created=Column(Float,nullable=False,default=now)
    finished=Column(Float)
class Attempt(Base):
    __tablename__='v2_attempts'
    id=Column(Integer,primary_key=True)
    task_id=Column(Integer,ForeignKey('v2_tasks.id'),nullable=False)
    started=Column(Float,nullable=False,default=now)
    finished=Column(Float)
    status=Column(String(30),nullable=False,default='running')
    error=Column(Text,nullable=False,default='')
class User(Base):
    __tablename__='v2_users'
    id=Column(Integer,primary_key=True)
    openid=Column(String(150),nullable=False,unique=True)
    created=Column(Float,nullable=False,default=now)
class Session(Base):
    __tablename__='v2_sessions'
    token_hash=Column(String(64),primary_key=True)
    user_id=Column(Integer,ForeignKey('v2_users.id'),nullable=False,index=True)
    expires=Column(Float,nullable=False)
class Favorite(Base):
    __tablename__='v2_favorites'
    user_id=Column(Integer,ForeignKey('v2_users.id'),primary_key=True)
    document_id=Column(Integer,ForeignKey('v2_documents.id'),primary_key=True)
    created=Column(Float,nullable=False,default=now)
class Follow(Base):
    __tablename__='v2_follows'
    id=Column(Integer,primary_key=True)
    user_id=Column(Integer,ForeignKey('v2_users.id'),nullable=False,index=True)
    region=Column(String(10),nullable=False,default='')
    topic=Column(String(100),nullable=False,default='')
    include_national=Column(Boolean,nullable=False,default=True)
    created=Column(Float,nullable=False,default=now)
    __table_args__=(UniqueConstraint('user_id','region','topic','include_national'),)
class Outbox(Base):
    __tablename__='v2_outbox'
    revision_id=Column(Integer,ForeignKey('v2_revisions.id'),primary_key=True)
    delivered=Column(Boolean,nullable=False,default=False)
class Notification(Base):
    __tablename__='v2_notifications'
    user_id=Column(Integer,ForeignKey('v2_users.id'),primary_key=True)
    revision_id=Column(Integer,ForeignKey('v2_revisions.id'),primary_key=True)
    read=Column(Boolean,nullable=False,default=False)
    created=Column(Float,nullable=False,default=now)
class Audit(Base):
    __tablename__='v2_audit'
    id=Column(Integer,primary_key=True)
    actor=Column(String(100),nullable=False)
    action=Column(String(100),nullable=False)
    target=Column(String(150),nullable=False)
    reason=Column(Text,nullable=False)
    before=Column(JSON,nullable=False,default=dict)
    after=Column(JSON,nullable=False,default=dict)
    created=Column(Float,nullable=False,default=now)
