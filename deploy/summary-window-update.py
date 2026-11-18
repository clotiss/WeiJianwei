"""Apply the three-year summary restriction and ten concurrent summary workers.

Run as ubuntu: python3 summary-window-update.py --revision <full Git commit SHA>
Downloads and verifies code before stopping the summary worker. Collection continues.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
import urllib.request

BACKEND = Path('/home/ubuntu/weijianwei-releases/20261118-6d4c0d4/backend')
ROOT = Path('/home/ubuntu/weijianwei-data/national-service')
EXPECTED_SHA256 = {
    'summaries.py': '0f373b80be4eb7ca9407dba69845d5a8dbb60348494fa14e3be7376651bc5623',
    'settings.py': 'a2f3b84e8f6743f2496739f8d07b9b3b3d0f13091f623b060349729c7e37ab6d',
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise SystemExit('A full Git commit SHA is required')
    for service in ('nhc-api', 'weijianwei-summary'):
        directory = run('systemctl', 'show', service, '--property=WorkingDirectory',
                        '--value', capture_output=True, text=True).stdout.strip()
        if Path(directory) != BACKEND:
            raise SystemExit('Unexpected active release; no changes made')
    sources = {}
    for name, expected in EXPECTED_SHA256.items():
        url = (f'https://raw.githubusercontent.com/clotiss/WeiJianwei/{args.revision}'
               f'/backend/policy_v2/{name}')
        with urllib.request.urlopen(url, timeout=60) as response:
            code = response.read()
        if hashlib.sha256(code).hexdigest() != expected:
            raise SystemExit('Source checksum mismatch; no changes made')
        compile(code, name, 'exec')
        sources[name] = code
    backup = Path('/home/ubuntu/weijianwei-backups') / f'summary-window-{time.time_ns()}'
    backup.mkdir(mode=0o700)
    for name in sources:
        shutil.copy2(BACKEND / 'policy_v2' / name, backup / name)
    config = ROOT / 'ai.env'
    shutil.copy2(config, backup / 'ai.env')
    (backup / 'ai.env').chmod(0o600)
    run('sudo', '-n', 'systemctl', 'stop', 'weijianwei-summary')
    try:
        with sqlite3.connect(ROOT / 'policy.db') as source, sqlite3.connect(backup / 'policy.db') as dest:
            source.backup(dest)
        for name, code in sources.items():
            target = BACKEND / 'policy_v2' / name
            staged = target.with_suffix('.py.next')
            staged.write_bytes(code)
            staged.chmod(0o644)
            os.replace(staged, target)
        lines = [line for line in config.read_text().splitlines()
                 if not re.match(r'^\s*(?:export\s+)?POLICY_AI_CONCURRENCY\s*=', line)]
        with tempfile.NamedTemporaryFile(mode='w', dir=ROOT, prefix='.ai-env-', delete=False) as staged:
            staged.write('\n'.join(lines + ['POLICY_AI_CONCURRENCY=10']) + '\n')
        os.replace(staged.name, config)
        # Use the existing venv, without printing or changing any credentials.
        run(str(BACKEND / 'venv/bin/python'), '-c', '''
import json
from collections import Counter
from sqlalchemy import select
from policy_v2.db import database
from policy_v2.models import Document, Revision
from policy_v2.summaries import enforce_summary_window, exclusion_reason, summary_window
from policy_v2.settings import Settings
settings = Settings(_env_file='/home/ubuntu/weijianwei-data/national-service/ai.env')
assert settings.ai_concurrency == 10
engine, factory = database('sqlite:////home/ubuntu/weijianwei-data/national-service/policy.db')
excluded = enforce_summary_window(factory)
with factory() as db:
    rows = db.execute(select(Revision.published, Revision.summary_status).join(
        Document, Document.current_revision == Revision.id).where(Document.status == 'ready')).all()
eligible = [state for published, state in rows if not exclusion_reason(published)]
print(json.dumps({'summary_window': [str(d) for d in summary_window()], 'total': len(rows),
    'concurrency': settings.ai_concurrency,
    'eligible': len(eligible), 'eligible_states': dict(Counter(eligible)),
    'excluded_unfinished_revisions': excluded}, ensure_ascii=False))
engine.dispose()
''', cwd=BACKEND)
        run('sudo', '-n', 'systemctl', 'restart', 'nhc-api')
        healthy = False
        for _ in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3) as response:
                    healthy = response.status == 200
                if healthy:
                    break
            except OSError:
                pass
            time.sleep(1)
        if not healthy:
            raise RuntimeError('API health check failed')
        run('sudo', '-n', 'systemctl', 'start', 'weijianwei-summary')
        run('systemctl', 'is-active', 'nhc-api', 'weijianwei-summary', 'weijianwei-worker')
        print(json.dumps({'deployed_revision': args.revision, 'backup': str(backup),
                          'code_sha256': EXPECTED_SHA256, 'concurrency': 10}))
    except Exception:
        # Do not resume the unrestricted worker after a partial update.
        run('sudo', '-n', 'systemctl', 'stop', 'weijianwei-summary')
        for name in sources:
            shutil.copy2(backup / name, BACKEND / 'policy_v2' / name)
        shutil.copy2(backup / 'ai.env', config)
        run('sudo', '-n', 'systemctl', 'restart', 'nhc-api')
        print('Update failed; API code restored, summary worker remains stopped. Backup:', backup)
        raise


if __name__ == '__main__':
    main()
