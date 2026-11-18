"""Deploy a complete source revision and apply the captured 434-summary repair."""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
import time
import urllib.request


def run(*args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    if not re.fullmatch('[0-9a-f]{40}', args.revision) or not re.fullmatch('[0-9a-f]{64}', args.source_sha256):
        parser.error('Expected full source revision and digest')
    root = Path('/home/ubuntu')
    release = root / 'weijianwei-releases' / args.revision
    data = root / 'weijianwei-data/national-service'
    with tempfile.TemporaryDirectory(prefix='policy-summary-repair-') as directory:
        script = Path(directory) / 'sync-release.py'
        url = f'https://raw.githubusercontent.com/clotiss/WeiJianwei/{args.revision}/deploy/sync-release.py'
        with urllib.request.urlopen(url, timeout=60) as response: script.write_bytes(response.read())
        run('python3', script, 'deploy', '--revision', args.revision, '--source-sha256', args.source_sha256)
    bundle = release / 'evidence/national/summary-repair-2026-11-18.json'
    payload = json.loads(bundle.read_text())
    if len(payload['items']) != 434: raise ValueError('Expected the captured 434-document cohort')
    backup = root / 'weijianwei-backups' / f'summary-repair-{time.time_ns()}'
    backup.mkdir(mode=0o700)
    print('Stopping background workers; backing up data before summary repair.', flush=True)
    run('sudo', '-n', 'systemctl', 'stop', 'weijianwei-worker', 'weijianwei-summary')
    try:
        with sqlite3.connect(data / 'policy.db') as source, sqlite3.connect(backup / 'policy.db') as target:
            source.backup(target)
        print('Applying verified summaries and original-media text. Existing successful summaries are preserved.', flush=True)
        run(release / 'backend/venv/bin/python', '-m', 'policy_v2.summary_repair',
            '--root', data, '--bundle', bundle, cwd=release / 'backend')
    finally:
        run('sudo', '-n', 'systemctl', 'start', 'weijianwei-worker', 'weijianwei-summary')
    run('systemctl', 'is-active', 'nhc-api', 'weijianwei-worker', 'weijianwei-summary')
    print(json.dumps({'status': 'repair_complete', 'cohort': 434, 'revision': args.revision,
                      'source_sha256': args.source_sha256, 'backup': str(backup)}), flush=True)


if __name__ == '__main__': main()
