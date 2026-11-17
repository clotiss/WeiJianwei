"""Isolated, bounded monitoring trial; never opens the application's default DB.

Example: python -m policy_v2.trial run --root .runtime/monitor-trial --sources
gd-policy nx-policy bj-policy --days 3 --once --max-minutes 30
"""
import argparse
import fcntl
import json
import math
import time
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import select
from .db import Base, database
from .models import CollectionRun, Document, Revision, Source, Task
from .rounds import summary, config_hash
from .settings import Settings
from .sources import seed, source_definitions
from .worker import run_workers


def prepare(root, source_ids, days):
    root = Path(root).resolve()
    marker = root/'trial.json'
    if marker.exists():
        metadata=json.loads(marker.read_text())
        if metadata.get('purpose')!='isolated_collection_trial' or sorted(metadata['sources'])!=sorted(source_ids) or metadata['days']!=days:
            raise ValueError('trial_configuration_mismatch')
    else:
        if root.exists() and any(root.iterdir()):
            raise ValueError('trial_root_must_be_empty')
        definitions={s['id']:s for s in source_definitions() if s.get('config')}
        if not 1<=len(set(source_ids))<=6 or any(s not in definitions for s in source_ids):
            raise ValueError('choose_1_to_6_configured_sources')
        if not 3<=days<=7:raise ValueError('trial_days_must_be_3_to_7')
        root.mkdir(parents=True,exist_ok=True)
        started=time.time()
        metadata={'purpose':'isolated_collection_trial','sources':sorted(set(source_ids)),
                  'days':days,'started':started,'deadline':started+days*86400}
        marker.write_text(json.dumps(metadata,ensure_ascii=False,indent=2)+'\n')
    settings=Settings(database_url='sqlite:///'+str(root/'trial.db'),object_root=root/'objects',
                      storage_backend='local',domain_delay_seconds=3)
    engine,factory=database(settings.database_url)
    Base.metadata.create_all(engine)
    seed(factory)
    with factory.begin() as db:
        for source in db.scalars(select(Source)):
            source.enabled=source.id in metadata['sources']
    return root,metadata,settings,engine,factory


def report(factory, metadata, now=None):
    now=time.time() if now is None else now
    rows=[]
    with factory() as db:
        for sid in metadata['sources']:
            source=db.get(Source,sid)
            runs=list(db.scalars(select(CollectionRun).where(CollectionRun.source_id==sid).order_by(CollectionRun.started)))
            complete=[r for r in runs if r.state=='succeeded' and metadata['started']<=r.finished<=metadata['deadline']]
            # A late inspection cannot turn a short smoke test into a multi-day pass.
            times=[metadata['started'],*sorted(r.finished for r in complete),min(now,metadata['deadline'])]
            max_gap=max((b-a for a,b in zip(times,times[1:])),default=0)
            minimum=math.floor(metadata['days']*86400/source.interval_seconds)
            unresolved=any(r.state!='succeeded' for r in runs)
            consistent=all(r.config_hash==config_hash(source) for r in runs)
            rows.append({'source':sid,'run':summary(db,sid),'completed_runs':len(complete),
                'required_runs':minimum,'max_completion_gap_seconds':max_gap,
                'documents':db.query(Document).filter_by(source_id=sid).count(),
                'configuration_consistent':consistent,
                'passed':consistent and now>=metadata['deadline'] and len(complete)>=minimum
                         and max_gap<=source.interval_seconds+7200 and not unresolved})
        tasks=list(db.scalars(select(Task)))
        counts={state:sum(t.state==state for t in tasks) for state in ('queued','running','succeeded','failed')}
    return {'started':metadata['started'],'deadline':metadata['deadline'],'checked_at':now,
            'verdict':('passed' if all(r['passed'] for r in rows) else 'needs_attention') if now>=metadata['deadline'] else 'observing',
            'sources':rows,'tasks':counts,'scope':'isolated_database; downloads_complete_does_not_mean_OCR_complete'}


def run(root, metadata, settings, factory, *, once=False, max_minutes=30):
    if time.time()>=metadata['deadline']:
        result=report(factory,metadata)
        (root/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        return 0 if result['verdict']=='passed' else 2
    stop=Event();errors=[]
    def work():
        try:run_workers(factory,settings,workers=2,stop=stop)
        except Exception as exc:errors.append(type(exc).__name__+':'+str(exc));stop.set()
    worker=Thread(target=work);worker.start()
    limit=min(metadata['deadline'],time.time()+max_minutes*60) if once else metadata['deadline']
    previous=None;last_write=0
    try:
        while True:
            result=report(factory,metadata)
            signature=json.dumps([(r['source'],r['run'],r['documents']) for r in result['sources']],sort_keys=True)
            if signature!=previous or time.time()-last_write>=60:
                (root/'report.json.tmp').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
                (root/'report.json.tmp').replace(root/'report.json')
                with (root/'observations.jsonl').open('a') as log:log.write(json.dumps(result,ensure_ascii=False)+'\n')
                if signature!=previous:
                    print(json.dumps({'verdict':result['verdict'],'sources':[
                        {'id':r['source'],'state':(r['run'] or {}).get('state'),'pages':(r['run'] or {}).get('pages_read'),
                         'documents':r['documents']} for r in result['sources']]},ensure_ascii=False),flush=True)
                previous=signature;last_write=time.time()
            warmup_complete=all(r['run'] and r['run']['state']=='succeeded' for r in result['sources'])
            if errors or time.time()>=limit or (once and warmup_complete):break
            stop.wait(5)
    finally:
        stop.set();worker.join()
        result=report(factory,metadata)
        if errors:result['worker_errors']=errors
        (root/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return 0 if not errors and (all(r['run'] and r['run']['state']=='succeeded' for r in result['sources']) if once else result['verdict']=='passed') else 2


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=['run','report'])
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--sources',nargs='+')
    parser.add_argument('--days',type=int,default=3)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--max-minutes',type=int,default=30)
    args=parser.parse_args()
    if args.command=='report':
        root=args.root.resolve();metadata=json.loads((root/'trial.json').read_text())
        engine,factory=database('sqlite:///'+str(root/'trial.db'))
        try:print(json.dumps(report(factory,metadata),ensure_ascii=False,indent=2))
        finally:engine.dispose()
        return
    if not args.sources:parser.error('--sources is required for run')
    if not 1<=args.max_minutes<=120:parser.error('--max-minutes must be 1 to 120')
    # Lock before initializing so two processes cannot change the same trial's setup.
    args.root.mkdir(parents=True,exist_ok=True)
    lock_path=args.root.parent/(args.root.name+'.lock')
    with lock_path.open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        root,metadata,settings,engine,factory=prepare(args.root,args.sources,args.days)
        try:code=run(root,metadata,settings,factory,once=args.once,max_minutes=args.max_minutes)
        finally:engine.dispose()
    raise SystemExit(code)


if __name__=='__main__':main()
