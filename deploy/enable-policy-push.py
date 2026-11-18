"""Synchronize a pinned release, validate WeChat configuration, then enable policy digests."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import urllib.request

TEMPLATE = 'vkf2X3KU8wf8htVnKZKFYWvgWyb0aG24BL_21G-GNbo'
SERVICES = ('nhc-api', 'weijianwei-worker', 'weijianwei-summary')


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
    with tempfile.TemporaryDirectory(prefix='policy-push-') as directory:
        script = Path(directory) / 'sync-release.py'
        url = f'https://raw.githubusercontent.com/clotiss/WeiJianwei/{args.revision}/deploy/sync-release.py'
        with urllib.request.urlopen(url, timeout=60) as response: script.write_bytes(response.read())
        run('python3', script, 'deploy', '--revision', args.revision, '--source-sha256', args.source_sha256)
    backup = root / 'weijianwei-backups' / f'policy-push-{time.time_ns()}'
    backup.mkdir(mode=0o700)
    private_env = data / 'ai.env'
    saved_env = backup / 'ai.env'
    print('Validating the existing app credentials and policy notification template.', flush=True)
    # Configuration never changes unless the live platform confirms template ownership and fields.
    run(release / 'backend/venv/bin/python', '-m', 'policy_v2.push_config', '--env', private_env,
        '--template', TEMPLATE, '--backup', saved_env, cwd=release / 'backend')
    try:
        run('sudo', '-n', 'systemctl', 'restart', 'nhc-api', 'weijianwei-worker')
        for attempt in range(30):
            try:
                with urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5) as response:
                    health = json.load(response)
                if (health.get('revision') == args.revision and health.get('source_sha256') == args.source_sha256
                        and health.get('wechat_push_available') is True): break
            except OSError: pass
            if attempt == 29: raise RuntimeError('Push configuration health check failed')
            time.sleep(1)
        run('systemctl', 'is-active', *SERVICES)
    except Exception:
        descriptor, name = tempfile.mkstemp(prefix='.push-rollback-', dir=private_env.parent)
        os.close(descriptor)
        shutil.copyfile(saved_env, name); os.chmod(name, 0o600); os.replace(name, private_env)
        run('sudo', '-n', 'systemctl', 'restart', 'nhc-api', 'weijianwei-worker')
        print('Push activation failed; the prior private configuration has been restored.', flush=True)
        raise
    print(json.dumps({'status':'policy_push_enabled','revision':args.revision,
        'source_sha256':args.source_sha256,'template':'政策更新通知','mode':'once',
        'send_time':'09:00 Asia/Shanghai','backup':str(backup)}, ensure_ascii=False), flush=True)


if __name__ == '__main__': main()
