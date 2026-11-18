"""One-time Tencent Ubuntu cutover. Run as ubuntu; secrets stay on the server.

python3 production-cutover.py stage|cutover|status|rollback
Uploads are expected in /home/ubuntu/nhc-project. Stage never stops the old API.
"""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tarfile
import time
import urllib.request

HOME = Path('/home/ubuntu')
OLD = HOME / 'nhc-project'
RELEASE = HOME / 'weijianwei-releases/20261118-6d4c0d4'
DATA = HOME / 'weijianwei-data/national-service'
BACKUP = HOME / 'weijianwei-backups/20261118-before-v2'
PYTHON = RELEASE / 'backend/venv/bin/python'
UNIT = Path('/etc/systemd/system/nhc-api.service')
CHECKSUMS = {
    'code.tar': 'b670f183ed65d225b61695af8e968d413bc8a64fabd6723c1bb9b9411e414836',
    'weijianwei-data.tar.gz': 'd29d133469c4debe463e67334b1c3a40f93c67fa34e80e0029c22628f7075d82',
}


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(*args):
    return subprocess.check_output([str(x) for x in args], text=True).strip()


def extract(path, destination):
    with tarfile.open(path) as archive:
        for entry in archive.getmembers():
            target = (destination / entry.name).resolve()
            if not target.is_relative_to(destination.resolve()) or entry.issym() or entry.islnk():
                raise ValueError('Unsafe archive member')
        archive.extractall(destination)


def get_json(path, port=8000):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=30) as response:
        return json.load(response)


def smoke(port):
    assert get_json('/health', port)['status'] == 'ok'
    rows = get_json('/api/v2/policies?limit=1', port)
    assert rows['total'] > 5000 and rows['items']
    detail = get_json('/api/v2/policies/506', port)
    assert detail['body'] and detail['summary_status']['state'] == 'ready', detail['summary_status']
    print(json.dumps({'port': port, 'documents': rows['total'],
                      'regions': len(get_json('/api/v2/regions', port)),
                      'summary_506': detail['summary_status']}, ensure_ascii=False), flush=True)


def prepare():
    assert output('systemctl', 'show', 'nhc-api', '-p', 'FragmentPath', '--value') == str(UNIT)
    assert not output('systemctl', 'show', 'nhc-api', '-p', 'DropInPaths', '--value'), 'Inspect service overrides first'
    for name, expected in CHECKSUMS.items():
        digest = hashlib.sha256()
        with (OLD / name).open('rb') as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b''):
                digest.update(chunk)
        assert digest.hexdigest() == expected, name + ' checksum mismatch'
        print(name + ' checksum OK', flush=True)
    BACKUP.mkdir(parents=True, exist_ok=False, mode=0o700)
    with sqlite3.connect(OLD / 'backend/nhc_policy.db') as source:
        with sqlite3.connect(BACKUP / 'nhc_policy.db') as destination:
            source.backup(destination)
            assert destination.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    run('tar', '-czf', BACKUP / 'legacy-code.tar.gz', '--exclude=backend/venv',
        '--exclude=venv', '--exclude=*.tar', '--exclude=*.tar.gz', '--exclude=*.db',
        '--exclude=__pycache__', '-C', OLD, '.')
    run('sudo', '-n', 'cp', '-a', UNIT, BACKUP / 'nhc-api.service')
    with (BACKUP / 'nginx.txt').open('w') as target:
        run('sudo', '-n', 'nginx', '-T', stdout=target, stderr=subprocess.STDOUT)
    pid = output('systemctl', 'show', 'nhc-api', '-p', 'MainPID', '--value')
    old_env = dict(item.split('=', 1) for item in Path('/proc/' + pid + '/environ')
                   .read_text().split('\0') if '=' in item)
    key = old_env.get('POLICY_AI_KEY') or old_env.get('DEEPSEEK_API_KEY')
    assert key, 'Existing AI key unavailable'
    RELEASE.mkdir(parents=True, exist_ok=False)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    assert not DATA.exists(), 'Refusing to overwrite existing production data'
    extract(OLD / 'code.tar', RELEASE)
    extract(OLD / 'weijianwei-data.tar.gz', DATA.parent)
    with sqlite3.connect(DATA / 'policy.db') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        print('Database integrity OK; documents:', db.execute('SELECT count(*) FROM v2_documents').fetchone()[0], flush=True)
    config = {
        'POLICY_AI_KEY': key,
        'POLICY_AI_MODEL': 'deepseek-v4-pro',
        'POLICY_AI_URL': 'https://api.deepseek.com/v1/chat/completions',
        'POLICY_AI_BATCH_SIZE': '100',
        'POLICY_DATABASE_URL': 'sqlite:///' + str(DATA / 'policy.db'),
        'POLICY_OBJECT_ROOT': str(DATA / 'objects'),
        'POLICY_PUBLIC_BASE': 'https://wjwjwjw.top',
    }
    for name in ('POLICY_WECHAT_APP_ID', 'POLICY_WECHAT_SECRET', 'POLICY_ADMIN_TOKEN'):
        if old_env.get(name):
            config[name] = old_env[name]
    fd = os.open(DATA / 'ai.env', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as target:
        for name, value in config.items():
            target.write(name + '=' + json.dumps(value) + '\n')
    (BACKUP / 'prepared').write_text('Snapshot and private config prepared\n')


def stage():
    if (BACKUP / 'staged').exists():
        raise RuntimeError('Already staged; inspect status before proceeding')
    if not (BACKUP / 'prepared').exists():
        prepare()
    run('python3', '-m', 'venv', RELEASE / 'backend/venv')
    run(PYTHON, '-m', 'pip', 'install', '-r', RELEASE / 'backend/requirements-v2.txt')
    run('sudo', '-n', PYTHON, '-m', 'playwright', 'install-deps', 'firefox')
    run(PYTHON, '-m', 'playwright', 'install', 'firefox')
    env = dict(os.environ, POLICY_AI_CONFIG_FILE=str(DATA / 'ai.env'))
    with (BACKUP / 'staging-api.log').open('w') as log:
        process = subprocess.Popen([str(PYTHON), '-m', 'uvicorn', 'policy_v2.app:app',
            '--host', '127.0.0.1', '--port', '8001'], cwd=RELEASE / 'backend',
            env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            for _ in range(60):
                try:
                    get_json('/health', 8001)
                    break
                except Exception:
                    if process.poll() is not None:
                        raise RuntimeError('Staging API failed; inspect private log')
                    time.sleep(1)
            smoke(8001)
        finally:
            process.terminate()
            process.wait(timeout=30)
    (BACKUP / 'staged').write_text('API smoke passed\n')
    print('STAGED_READY', flush=True)


def install_unit(name, command):
    text = f'''[Unit]
Description=WeiJianwei V2 {name}
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory={RELEASE}/backend
Environment=PYTHONUNBUFFERED=1
Environment=POLICY_AI_CONFIG_FILE={DATA}/ai.env
ExecStart={PYTHON} {command}
Restart=on-failure
RestartSec=10
TimeoutStopSec=120
UMask=0077

[Install]
WantedBy=multi-user.target
'''
    path = BACKUP / (name + '.new.service')
    path.write_text(text)
    run('sudo', '-n', 'install', '-m', '644', path, '/etc/systemd/system/' + name + '.service')


def rollback():
    run('sudo', '-n', 'systemctl', 'disable', '--now', 'weijianwei-worker', 'weijianwei-summary')
    run('sudo', '-n', 'cp', '-a', BACKUP / 'nhc-api.service', UNIT)
    run('sudo', '-n', 'systemctl', 'daemon-reload')
    run('sudo', '-n', 'systemctl', 'restart', 'nhc-api')
    print('ROLLED_BACK_TO_LEGACY', flush=True)


def cutover():
    assert (BACKUP / 'staged').exists(), 'Stage must pass first'
    assert not (BACKUP / 'live').exists(), 'Already switched'
    install_unit('nhc-api', '-m uvicorn policy_v2.app:app --host 127.0.0.1 --port 8000')
    install_unit('weijianwei-worker', f'-m policy_v2.national_service worker --root {DATA} --workers 1')
    install_unit('weijianwei-summary', f'-m policy_v2.national_service summary --root {DATA}')
    try:
        run('sudo', '-n', 'systemctl', 'daemon-reload')
        run('sudo', '-n', 'systemctl', 'restart', 'nhc-api')
        for _ in range(30):
            try:
                get_json('/api/v2/regions')
                break
            except Exception:
                time.sleep(1)
        smoke(8000)
        run('sudo', '-n', 'systemctl', 'enable', '--now', 'nhc-api', 'weijianwei-worker', 'weijianwei-summary')
        (BACKUP / 'live').write_text('V2 live\n')
    except Exception:
        rollback()
        raise
    status()


def status():
    run('systemctl', 'is-active', 'nhc-api', 'weijianwei-worker', 'weijianwei-summary')
    smoke(8000)
    with sqlite3.connect(DATA / 'policy.db') as db:
        print('Summary states:', db.execute('SELECT summary_status,count(*) FROM v2_revisions GROUP BY summary_status').fetchall())


if __name__ == '__main__':
    os.umask(0o077)
    actions = {'stage': stage, 'cutover': cutover, 'status': status, 'rollback': rollback}
    if len(sys.argv) != 2 or sys.argv[1] not in actions:
        raise SystemExit('Usage: production-cutover.py stage|cutover|status|rollback')
    actions[sys.argv[1]]()
