"""Run a local V2 API for the new mini-program, optionally from a read-only DB snapshot.
Never starts collection workers or changes the source database.
"""
import argparse
import os
import sqlite3
import tempfile
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot-from', type=Path, help='Read-only SQLite source, e.g. the monitoring trial DB')
    parser.add_argument('--port', type=int, default=8891)
    args = parser.parse_args()
    if args.snapshot_from and not args.snapshot_from.is_file():
        parser.error('Snapshot source does not exist')
    with tempfile.TemporaryDirectory(prefix='weijianwei-preview-') as root:
        target = Path(root) / 'preview.db'
        if args.snapshot_from:
            with sqlite3.connect(args.snapshot_from.resolve().as_uri() + '?mode=ro', uri=True) as source:
                with sqlite3.connect(target) as destination:
                    source.backup(destination)
        os.environ['POLICY_DATABASE_URL'] = 'sqlite:///' + str(target)
        os.environ['POLICY_OBJECT_ROOT'] = str(Path(root) / 'objects')
        # This disposable preview cannot send account requests to WeChat or expose copied sessions.
        os.environ['POLICY_WECHAT_APP_ID'] = ''
        os.environ['POLICY_WECHAT_SECRET'] = ''
        os.environ['POLICY_ADMIN_TOKEN'] = ''
        from policy_v2.app import app, SessionLocal
        from policy_v2.models import Source, Session
        with SessionLocal.begin() as db:
            db.query(Source).update({Source.enabled:False})
            db.query(Session).delete()
        import uvicorn
        print(f'Local read preview: http://127.0.0.1:{args.port}/api/v2 (temporary snapshot; account login disabled)', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port)


if __name__ == '__main__':
    main()
