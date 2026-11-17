"""Database leases serialize requests to a host across workers and restarts."""
import time
import uuid
from contextlib import contextmanager
from threading import Event, Thread
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from .db import transaction
from .models import DomainState


class DomainBusy(Exception):
    def __init__(self, until):
        super().__init__('domain_busy')
        self.until = until


def acquire(factory, host, seconds=300, now=None):
    now = time.time() if now is None else now
    owner = uuid.uuid4().hex
    with transaction(factory) as db:
        if db.get(DomainState, host) is None:
            try:
                with db.begin_nested():
                    db.add(DomainState(host=host)); db.flush()
            except IntegrityError: pass
        changed = db.execute(update(DomainState).where(DomainState.host==host,
            DomainState.lease_until<=now, DomainState.next_allowed<=now,
            DomainState.cooldown_until<=now).values(owner=owner,lease_until=now+seconds))
        if changed.rowcount != 1:
            row=db.get(DomainState,host); db.refresh(row)
            raise DomainBusy(max(row.lease_until,row.next_allowed,row.cooldown_until))
    return owner


def renew(factory,host,owner,seconds):
    with transaction(factory) as db:
        return db.execute(update(DomainState).where(DomainState.host==host,DomainState.owner==owner)
            .values(lease_until=time.time()+seconds)).rowcount==1


def release(factory,host,owner,delay,now=None):
    now=time.time() if now is None else now
    with transaction(factory) as db:
        return db.execute(update(DomainState).where(DomainState.host==host,DomainState.owner==owner)
            .values(owner=None,lease_until=0,next_allowed=now+delay)).rowcount==1


def cool_down(factory,hosts,seconds):
    until=time.time()+seconds
    with transaction(factory) as db:
        for host in hosts:
            row=db.get(DomainState,host)
            if row is not None:row.cooldown_until=max(row.cooldown_until,until)


@contextmanager
def lease(factory,host,delay,seconds=300):
    owner=acquire(factory,host,seconds); stop=Event(); lost=Event()
    def keep():
        while not stop.wait(max(1,seconds/3)):
            try:
                if not renew(factory,host,owner,seconds): lost.set(); return
            except Exception: lost.set(); return
    thread=Thread(target=keep,daemon=True);thread.start()
    try:
        yield
        if lost.is_set(): raise RuntimeError('domain_lease_lost')
    finally:
        stop.set();thread.join();release(factory,host,owner,delay)
