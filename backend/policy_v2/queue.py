import random
import uuid
from contextlib import contextmanager
from threading import Event, Thread
from sqlalchemy import select,or_,and_,update
from sqlalchemy.exc import IntegrityError
from .models import Task,Attempt,now
from .db import transaction

def enqueue(db,kind,key,payload,priority=10):
    existing=db.scalar(select(Task).where(Task.key==key))
    if existing:return existing
    try:
        with db.begin_nested():
            task=Task(kind=kind,key=key,payload=payload,priority=priority);db.add(task);db.flush()
        return task
    except IntegrityError:return db.scalar(select(Task).where(Task.key==key))

def claim(factory,lease_seconds=300,clock=None,kinds=None):
    t=now() if clock is None else clock;owner=uuid.uuid4().hex
    with transaction(factory) as db:
        eligible=or_(and_(Task.state=='queued',Task.available<=t),and_(Task.state=='running',Task.lease_until<t))
        q=select(Task).where(eligible).order_by(Task.priority,Task.id).limit(1).with_for_update(skip_locked=True)
        if kinds is not None:q=q.where(Task.kind.in_(kinds))
        task=db.scalar(q)
        if not task:return None
        changed=db.execute(update(Task).where(Task.id==task.id,eligible).values(state='running',owner=owner,lease_until=t+lease_seconds,attempts=Task.attempts+1))
        if changed.rowcount!=1:return None
        db.refresh(task)
        db.add(Attempt(task_id=task.id,started=t))
        return dict(id=task.id,kind=task.kind,payload=task.payload,owner=owner,attempts=task.attempts)

def heartbeat(factory,task,lease):
    with transaction(factory) as db:
        return db.execute(update(Task).where(Task.id==task['id'],Task.owner==task['owner'],Task.state=='running').values(lease_until=now()+lease)).rowcount==1


class TaskLeaseLost(Exception): pass


def assert_ownership(db, task):
    row=db.scalar(select(Task).where(Task.id==task['id']).with_for_update())
    if not row or row.owner!=task['owner'] or row.state!='running' or row.lease_until<now():
        raise TaskLeaseLost('task_lease_lost')


@contextmanager
def keep_lease(factory, task, seconds):
    stop=Event()
    def renew():
        while not stop.wait(max(.1,seconds/3)):
            try:
                if not heartbeat(factory,task,seconds):return
            except Exception:return  # The write transaction rechecks ownership before persisting.
    thread=Thread(target=renew,daemon=True);thread.start()
    try:yield
    finally:stop.set();thread.join()

def finish(factory,task,error=None,max_attempts=3,retry_at=0):
    with transaction(factory) as db:
        row=db.scalar(select(Task).where(Task.id==task['id']).with_for_update())
        if not row or row.owner!=task['owner']:return False
        row.lease_until=None;row.owner=None;row.error=(error or '')[:1000]
        row.state='succeeded' if error is None else ('failed' if row.attempts>=max_attempts else 'queued')
        row.available=max(retry_at,now()+min(3600,30*2**row.attempts)+random.random()*5)
        row.finished=now() if row.state in ('succeeded','failed') else None
        attempt=db.scalar(select(Attempt).where(Attempt.task_id==row.id,Attempt.status=='running').order_by(Attempt.id.desc()).limit(1))
        if attempt:attempt.finished=now();attempt.status='succeeded' if error is None else 'failed';attempt.error=row.error
        return True


def defer(factory, task, until):
    """Postpone a claimed task without consuming an attempt or issuing a request."""
    with transaction(factory) as db:
        row = db.get(Task, task['id'])
        if not row or row.owner != task['owner'] or row.state != 'running':
            return False
        row.state = 'queued'
        row.available = until
        row.attempts = max(0, row.attempts - 1)
        row.owner = None
        row.lease_until = None
        attempt = db.scalar(select(Attempt).where(Attempt.task_id == row.id, Attempt.status == 'running').order_by(Attempt.id.desc()).limit(1))
        if attempt:
            attempt.finished = now()
            attempt.status = 'deferred'
        return True
