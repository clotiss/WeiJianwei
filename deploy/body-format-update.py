"""Deploy paragraph-preserving reading text without changing saved data or AI jobs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
import urllib.request

BACKEND = Path('/home/ubuntu/weijianwei-releases/20261118-6d4c0d4/backend')
EXPECTED = {
    'app.py': '2aa4d5d29f7657e80bc11b36b0c4c76d09c401a7dd630b9d4b937caeb1001891',
    'parsing.py': '39efe610ba3b24158c2b49bdcb4f5e83ac992b31ff4f2b6cee0a843d36c5780f',
    'body_display.py': 'e24d99186de9b13edf4d4947fd8e9edb79009451ac15c7b3e1ca65449c42972e',
}


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[0-9a-f]{40}', args.revision):
        raise SystemExit('A full Git commit SHA is required')
    directory = run('systemctl', 'show', 'nhc-api', '--property=WorkingDirectory',
                    '--value', capture_output=True, text=True).stdout.strip()
    if Path(directory) != BACKEND:
        raise SystemExit('Unexpected active release; no changes made')
    sources = {}
    for name, expected in EXPECTED.items():
        url = f'https://raw.githubusercontent.com/clotiss/WeiJianwei/{args.revision}/backend/policy_v2/{name}'
        with urllib.request.urlopen(url, timeout=60) as response:
            code = response.read()
        if hashlib.sha256(code).hexdigest() != expected:
            raise SystemExit('Source checksum mismatch; no changes made')
        compile(code, name, 'exec')
        sources[name] = code
    backup = Path('/home/ubuntu/weijianwei-backups') / f'body-format-{time.time_ns()}'
    backup.mkdir(mode=0o700)
    for name in sources:
        target = BACKEND / 'policy_v2' / name
        if target.exists(): shutil.copy2(target, backup / name)
    run('sudo', '-n', 'systemctl', 'stop', 'nhc-api')
    try:
        for name, code in sources.items():
            target = BACKEND / 'policy_v2' / name
            staged = target.with_suffix('.py.next')
            staged.write_bytes(code)
            staged.chmod(0o644)
            os.replace(staged, target)
        run('sudo', '-n', 'systemctl', 'start', 'nhc-api')
        for attempt in range(20):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3) as response:
                    if response.status == 200: break
            except OSError:
                if attempt == 19: raise
                time.sleep(1)
        with urllib.request.urlopen('http://127.0.0.1:8000/api/v2/policies/285', timeout=15) as response:
            item = json.load(response)
        body = item.get('display_body', '')
        for expected in ('2026年10月20日', '国家卫生健康委办公厅', '请遵照执行。', '第十一条'):
            if expected not in body:
                raise RuntimeError('Reading layout verification failed')
        if re.sub(r'\s+', '', body) != re.sub(r'\s+', '', item['body']):
            raise RuntimeError('Reading text differs from saved wording')
        run('systemctl', 'is-active', 'nhc-api', 'weijianwei-summary', 'weijianwei-worker')
        print(json.dumps({'deployed_revision': args.revision, 'backup': str(backup),
                          'verified_document': 285, 'reading_layout': 'passed'}))
    except Exception:
        run('sudo', '-n', 'systemctl', 'stop', 'nhc-api')
        for name in sources:
            target = BACKEND / 'policy_v2' / name
            if (backup / name).exists(): shutil.copy2(backup / name, target)
            else: target.unlink(missing_ok=True)
        run('sudo', '-n', 'systemctl', 'start', 'nhc-api')
        print('Update failed; original API code restored. Backup:', backup)
        raise


if __name__ == '__main__':
    main()
