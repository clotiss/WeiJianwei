"""Durable sweep boundaries, bounded repair batches and whole-run accounting.

Only this module advances Source.last_success. A successful HTTP request is not
a successful collection run. Existing tables need no ALTER migration.
"""
import hashlib
import json
import time
from collections import Counter

from sqlalchemy import select, update
from .db import transaction
from .models import CollectionRun, RunTask, Source, Task, TaskRepair
from .queue import enqueue
from .settings import Settings
from .source_health import cooldown_until


def config_hash(source):
    value = json.dumps({'url':source.url, 'config':source.config}, sort_keys=True)
    return hashlib.sha256(value.encode()).hexdigest()


def link_task(db, run_id, task):
    if run_id and not db.get(RunTask, (run_id, task.id)):
        db.add(RunTask(run_id=run_id, task_id=task.id))
        db.flush()
    return task


def _list_task(db, source, run, url, page):
    key = f'run:{run.id}:list:' + hashlib.sha256(url.encode()).hexdigest()
    task = enqueue(db, 'list', key, {'source_id':source.id, 'run_id':run.id,
        'url':url, 'page_number':page, 'bucket':run.bucket,
        'batch_end':page + min(100, max(1, int(source.config.get('max_pages',3)))) - 1})
    return link_task(db, run.id, task)


def tasks_for_run(db, run_id):
    return list(db.scalars(select(Task).join(RunTask, RunTask.task_id==Task.id)
                          .where(RunTask.run_id==run_id).order_by(Task.id)))


def refresh_source(db, source, settings=None):
    """Derive state from committed dependency tasks, never from one child result."""
    settings = settings or Settings()
    runs = list(db.scalars(select(CollectionRun).where(CollectionRun.source_id==source.id,
        CollectionRun.state!='succeeded').order_by(CollectionRun.id)))
    errors = []
    for run in runs:
        tasks = tasks_for_run(db, run.id)
        counts = Counter(t.state for t in tasks)
        exhausted = sum(t.state=='failed' and (db.get(TaskRepair,t.id).cycles if db.get(TaskRepair,t.id) else 0)>=settings.repair_max_cycles for t in tasks)
        run.counts = {**dict(counts), 'total':len(tasks),
            'repair_exhausted':exhausted,
            **{kind:sum(t.kind==kind for t in tasks) for kind in ('list','detail','attachment')}}
        run.error = run.stop_reason or next((t.error for t in tasks if t.state!='succeeded' and t.error), '')
        if not source.enabled:
            run.state = 'paused'
        elif run.stop_reason:
            run.state = 'blocked'
        elif counts['failed']:
            run.state = 'blocked' if exhausted else 'repairing'
        elif run.listing_complete and tasks and counts['succeeded']==len(tasks):
            run.state = 'succeeded'
            run.finished = time.time()
            source.last_success = max(source.last_success or 0, run.finished)
        elif not counts['running'] and not counts['queued'] and run.next_url:
            run.state = 'waiting'
        else:
            run.state = 'running'
        if run.error:
            errors.append(run.error)
    # Queued tasks from before the upgrade have no run link. Their failures
    # remain visible until recovered; adding round accounting must not hide them.
    legacy_error=db.scalar(select(Task.error).where(Task.state!='succeeded',Task.error!='',
        Task.payload['source_id'].as_string()==source.id,
        ~Task.id.in_(select(RunTask.task_id))).order_by(Task.id.desc()).limit(1))
    source.last_error = errors[-1] if errors else (legacy_error or '')


def settle(factory, source_id, settings=None):
    with transaction(factory) as db:
        # Serialize scheduler/settlement on SQLite too, where FOR UPDATE is ignored.
        db.execute(update(Source).where(Source.id==source_id).values(last_scheduled=Source.last_scheduled))
        source = db.get(Source, source_id)
        if source:
            refresh_source(db, source, settings)


def _repair_due(db, source, settings):
    if cooldown_until(source)>time.time():
        return 0
    failed = list(db.scalars(select(Task).where(Task.state=='failed', Task.available<=time.time(),
        Task.payload['source_id'].as_string()==source.id)))
    count = 0
    for task in failed:
        repair = db.get(TaskRepair, task.id)
        if repair is None:
            repair = TaskRepair(task_id=task.id, cycles=0)
            db.add(repair)
        if repair.cycles>=settings.repair_max_cycles:
            continue
        repair.cycles += 1
        task.state = 'queued'
        task.attempts = 0
        task.finished = None
        task.owner = None
        task.lease_until = None
        count += 1
    return count


def defer_repair(factory, task, settings):
    with transaction(factory) as db:
        row = db.get(Task, task['id'])
        if row and row.state=='failed':
            row.available = max(row.available, time.time()+max(60,settings.repair_delay_seconds))
            if not db.get(TaskRepair, row.id):
                db.add(TaskRepair(task_id=row.id, cycles=0))


def discover(factory, source_id, settings=None):
    settings = settings or Settings()
    with transaction(factory) as db:
        locked = db.execute(update(Source).where(Source.id==source_id, Source.enabled.is_(True))
                            .values(last_scheduled=Source.last_scheduled))
        if not locked.rowcount:
            return 0
        source = db.get(Source, source_id)
        repaired = _repair_due(db, source, settings)
        db.flush()
        refresh_source(db, source, settings)
        # Continue the saved listing before starting a new sweep. Finished listings
        # with pending attachment repairs do not prevent the next scheduled sweep.
        run = db.scalar(select(CollectionRun).where(CollectionRun.source_id==source_id,
            CollectionRun.listing_complete.is_(False)).order_by(CollectionRun.id).limit(1))
        if run:
            if run.config_hash!=config_hash(source):
                run.stop_reason='source_config_changed'
                refresh_source(db, source, settings)
                return repaired
            if run.stop_reason=='scan_page_limit' and run.pages_read<settings.max_scan_pages:
                run.stop_reason=''
            if run.stop_reason:
                return repaired
            list_tasks = [t for t in tasks_for_run(db,run.id) if t.kind=='list']
            if any(t.state!='succeeded' for t in list_tasks):
                return repaired
            if run.next_url:
                _list_task(db,source,run,run.next_url,run.pages_read+1)
                run.state='running'
                return repaired+1
            return repaired
        bucket = int(time.time() // max(60,source.interval_seconds))
        existing = db.scalar(select(CollectionRun.id).where(CollectionRun.source_id==source_id,
                                                            CollectionRun.bucket==bucket))
        if existing:
            return repaired
        run = CollectionRun(source_id=source_id,bucket=bucket,config_hash=config_hash(source),next_url=source.url)
        db.add(run);db.flush()
        _list_task(db,source,run,source.url,1)
        source.last_scheduled=time.time()
        return repaired+1


def advance_listing(db, source, task, next_url, settings):
    run_id = task['payload'].get('run_id')
    if not run_id:
        return False  # Legacy queued tasks use their original bounded pagination.
    run = db.get(CollectionRun, run_id)
    page = int(task['payload']['page_number'])
    if page<run.pages_read:
        return True  # Replay after a crash must not rewind a committed cursor.
    run.pages_read = page
    run.next_url = next_url
    run.listing_complete = not next_url
    if not next_url:
        return True
    key = f'run:{run.id}:list:' + hashlib.sha256(next_url.encode()).hexdigest()
    repeated = db.scalar(select(Task).where(Task.key==key))
    if repeated and int(repeated.payload['page_number'])<=page:
        run.stop_reason = 'pagination_cycle'
    elif page>=settings.max_scan_pages:
        run.stop_reason = 'scan_page_limit'
    elif page<int(task['payload']['batch_end']):
        following = _list_task(db,source,run,next_url,page+1)
        following.payload={**following.payload, 'batch_end':task['payload']['batch_end']}
    return True


def summary(db, source_id):
    run = db.scalar(select(CollectionRun).where(CollectionRun.source_id==source_id)
                    .order_by(CollectionRun.id.desc()).limit(1))
    if not run:
        return None
    unresolved = db.scalar(select(CollectionRun.id).where(CollectionRun.source_id==source_id,
        CollectionRun.error!='').limit(1))
    return {'id':run.id, 'state':run.state, 'started':run.started, 'finished':run.finished,
            'listing_complete':run.listing_complete, 'pages_read':run.pages_read,
            'counts':run.counts, 'error':run.error, 'has_unresolved_failures':bool(unresolved)}
