"""Persistent nationwide development service; API and workers use the same DB and objects."""
import argparse
import fcntl
import json
import os
import signal
import time
from pathlib import Path
from threading import Event, Thread

from sqlalchemy import func, select, text
from .db import Base, database
from .models import Audit, Document, Source, Task
from .settings import Settings
from .sources import seed, source_definitions


def open_service(root):
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=True)
    marker = root / 'service.json'
    if marker.exists():
        if json.loads(marker.read_text()).get('purpose') != 'persistent_national_policy_service':
            raise ValueError('service_root_purpose_mismatch')
    elif any(root.iterdir()):
        raise ValueError('new_service_root_must_be_empty')
    else:
        marker.write_text(json.dumps({'purpose': 'persistent_national_policy_service', 'version': 1}) + '\n')
    settings = Settings(_env_file=root / 'ai.env', database_url='sqlite:///' + str(root / 'policy.db'), object_root=root / 'objects',
        storage_backend='local', domain_delay_seconds=3)
    engine, factory = database(settings.database_url)
    with engine.connect() as db:
        db.execute(text('PRAGMA journal_mode=WAL'))
    Base.metadata.create_all(engine)
    seed(factory)
    return settings, engine, factory


def enable_verified(factory):
    expected = {s['id'] for s in source_definitions() if s.get('config') and s['status'] == 'sample_pass'}
    with factory.begin() as db:
        rows = list(db.scalars(select(Source)))
        if not expected.issubset({s.id for s in rows}):
            raise ValueError('verified_source_registry_incomplete')
        if any(not (s.checkpoint or {}).get('verified_import') for s in rows if s.id in expected):
            raise ValueError('import_verified_pages_before_activation')
        for source in rows:
            source.enabled = source.id in expected
            source.interval_seconds = 21600
        for task in db.scalars(select(Task).where(Task.state == 'queued')):
            task.priority = {'list': 5, 'detail': 10, 'attachment': 20}.get(task.kind, 10)
        db.add(Audit(actor='national-service', action='sources.enable_verified', target='national',
            reason='User requested 28 provinces and national backfill plus routine monitoring',
            after={'sources': sorted(expected), 'interval_seconds': 21600}))
    return len(expected)


def report(factory):
    from .coverage import collection_status
    with factory() as db:
        return {'checked_at': time.time(), 'regions': dict(db.execute(select(Document.region, func.count()).where(Document.status == 'ready')
                    .group_by(Document.region)).all()),
                'tasks': dict(db.execute(select(Task.state, func.count()).group_by(Task.state)).all()),
                'sources': [collection_status(db, s) for s in db.scalars(select(Source).order_by(Source.id))]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['import', 'enable', 'api', 'worker', 'report', 'summary', 'summary-backfill', 'summary-report', 'summary-retry'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, default=Path.cwd())
    parser.add_argument('--workers', type=int, default=6)
    parser.add_argument('--port', type=int, default=8892)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()
    settings, engine, factory = open_service(args.root)
    try:
        if args.command == 'import':
            from .verified_import import import_verified
            root = args.workspace
            result = import_verified(factory, settings, root / 'evidence/national/trials-final.json', workspace=root,
                attachment_report=root / 'evidence/national/attachments-final.json',
                attachment_root=root / '.runtime/national/attachment-objects')
            print(json.dumps(result, ensure_ascii=False), flush=True)
        elif args.command == 'enable':
            print(json.dumps({'enabled': enable_verified(factory)}))
        elif args.command == 'report':
            print(json.dumps(report(factory), ensure_ascii=False, indent=2))
        elif args.command in ('summary-backfill', 'summary-report', 'summary-retry'):
            from .summaries import schedule_batch, report_summaries, retry_failed
            if not 1 <= args.limit <= 10000: parser.error('limit must be between 1 and 10000')
            if args.command == 'summary-backfill': print(json.dumps({'queued': schedule_batch(factory, settings, args.limit)}))
            if args.command == 'summary-retry': print(json.dumps({'retried': retry_failed(factory, args.limit)}))
            print(json.dumps(report_summaries(factory, settings), ensure_ascii=False, indent=2))
        elif args.command == 'summary':
            from .summaries import run_summary_worker
            stop = Event()
            for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, lambda *_: stop.set())
            with (args.root / 'summary.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                run_summary_worker(factory, settings, stop, settings_loader=lambda: Settings(_env_file=args.root / 'ai.env'))
        elif args.command == 'api':
            os.environ['POLICY_DATABASE_URL'] = settings.database_url
            os.environ['POLICY_OBJECT_ROOT'] = str(settings.object_root)
            os.environ['POLICY_STORAGE_BACKEND'] = 'local'
            os.environ['POLICY_AI_CONFIG_FILE'] = str(args.root.resolve() / 'ai.env')
            # A local development API must not reuse production account credentials.
            os.environ['POLICY_WECHAT_APP_ID'] = ''
            os.environ['POLICY_WECHAT_SECRET'] = ''
            os.environ['POLICY_ADMIN_TOKEN'] = ''
            import uvicorn
            uvicorn.run('policy_v2.app:app', host='127.0.0.1', port=args.port)
        else:
            from .worker import run_workers
            stop = Event()
            for sig in (signal.SIGTERM, signal.SIGINT):
                signal.signal(sig, lambda *_: stop.set())
            with (args.root / 'worker.lock').open('w') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                def observe():
                    while not stop.is_set():
                        try:
                            state = report(factory)
                            temporary = args.root / 'report.json.tmp'
                            temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n')
                            temporary.replace(args.root / 'report.json')
                            print(json.dumps({'documents': sum(state['regions'].values()),
                                'regions': len(state['regions']), 'tasks': state['tasks'],
                                'history_complete': sum(s['history_state'] == 'complete' for s in state['sources'])}), flush=True)
                        except Exception as exc:
                            print('National status report failed: ' + type(exc).__name__, flush=True)
                        stop.wait(60)
                observer = Thread(target=observe, daemon=True)
                observer.start()
                try:
                    run_workers(factory, settings, workers=args.workers, stop=stop)
                finally:
                    stop.set(); observer.join()
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
