"""Deploy an entire pinned checkout; verify the same source digest on both machines.

Local:  python3 deploy/sync-release.py fingerprint
Server: python3 sync-release.py deploy --revision SHA --source-sha256 DIGEST
Database, secrets, dependencies and developer-private settings are not source code.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import sqlite3
import subprocess
import tarfile
import time
import urllib.request

SERVER_ROOT = Path('/home/ubuntu')
DATA = SERVER_ROOT / 'weijianwei-data/national-service'
SERVICES = ('nhc-api', 'weijianwei-worker', 'weijianwei-summary')
MANIFEST = 'release-manifest.json'


def run(*args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def output(*args):
    return run(*args, capture_output=True, text=True).stdout.strip()


def included(name):
    path = PurePosixPath(name)
    return (not set(path.parts).intersection({'.git', '.runtime', '.venv', 'venv', '__pycache__', '.pytest_cache'})
            and path.suffix not in {'.db', '.sqlite', '.sqlite3', '.pyc'}
            and path.name not in {'.env', 'project.private.config.json'}
            and not path.name.startswith('.env.') and name != MANIFEST)


def source_manifest(root, names):
    files = {}
    for name in sorted(names):
        if not included(name): continue
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError('Source must be a regular file: ' + name)
        contents = path.read_bytes()
        if name == 'miniprogram/project.config.json':
            # The IDE rewrites key order/newlines. Compare actual public project
            # settings without committing or overwriting the user's local edit.
            contents = json.dumps(json.loads(contents), sort_keys=True, separators=(',', ':')).encode()
        files[name] = hashlib.sha256(contents).hexdigest()
    digest = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return {'source_sha256': digest, 'files': files}


def local_manifest(root):
    names = run('git', '-C', root, 'ls-files', '-z', capture_output=True).stdout.decode().split('\0')
    result = source_manifest(root, [name for name in names if name])
    result['revision'] = output('git', '-C', root, 'rev-parse', 'HEAD')
    return result


def extract_source(data, destination):
    names = set()
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        members = archive.getmembers()
        if sum(member.size for member in members) > 128 * 1024 * 1024:
            raise ValueError('Archive is unexpectedly large')
        for member in members:
            parts = PurePosixPath(member.name).parts
            if member.name.startswith('/') or '..' in parts or not parts:
                raise ValueError('Unsafe archive path')
            if member.isdir(): continue
            if not member.isfile() or len(parts) < 2:
                raise ValueError('Archive contains a link or special file')
            name = '/'.join(parts[1:])
            if not included(name): continue
            if name in names: raise ValueError('Duplicate archive path')
            names.add(name)
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.extractfile(member) as source:
                target.write_bytes(source.read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
    return source_manifest(destination, names)


def service_unit(original, previous, release, revision, digest):
    if f'WorkingDirectory={previous}/backend' not in original or f'{previous}/backend/venv/bin/python' not in original:
        raise ValueError('Unexpected service paths')
    text = original.replace(str(previous), str(release))
    text = re.sub(r'^Environment=POLICY_RELEASE_REVISION=.*\n?', '', text, flags=re.M)
    text = re.sub(r'^Environment=POLICY_SOURCE_SHA256=.*\n?', '', text, flags=re.M)
    if text.count('[Service]') != 1: raise ValueError('Unexpected service section')
    return text.replace('[Service]', '[Service]\nEnvironment=POLICY_RELEASE_REVISION=' + revision
                        + '\nEnvironment=POLICY_SOURCE_SHA256=' + digest)


def get_json(port, path):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}{path}', timeout=10) as response:
        return json.load(response)


def smoke(port, revision, digest):
    for attempt in range(30):
        try:
            health = get_json(port, '/health')
            if health.get('status') == 'ok' and health.get('revision') == revision and health.get('source_sha256') == digest: break
        except OSError:
            pass
        if attempt == 29: raise RuntimeError('Health or revision verification failed')
        time.sleep(1)
    total = get_json(port, '/api/v2/policies?limit=1')['total']
    if total <= 0: raise RuntimeError('Production policies are missing')
    for did, text in ((281, '各省、自治区、直辖市'), (285, '2026年10月20日')):
        detail = get_json(port, f'/api/v2/policies/{did}')
        if text not in detail.get('display_body', ''): raise RuntimeError('Reading layout regression')
    state = get_json(port, '/api/v2/policies/6320')['summary_status']['state']
    if state not in ('outside_summary_window', 'ready'): raise RuntimeError('Summary date scope regression')
    return total


def deploy(revision, expected):
    if not re.fullmatch(r'[0-9a-f]{40}', revision) or not re.fullmatch(r'[0-9a-f]{64}', expected):
        raise ValueError('Full revision and SHA256 digest are required')
    units, previous = {}, None
    for name in SERVICES:
        if output('systemctl', 'show', name, '-p', 'DropInPaths', '--value'):
            raise ValueError('Service overrides need inspection before synchronization')
        directory = Path(output('systemctl', 'show', name, '-p', 'WorkingDirectory', '--value'))
        if directory.name != 'backend' or directory.parent.parent != SERVER_ROOT / 'weijianwei-releases':
            raise ValueError('Unexpected production directory')
        if previous is not None and directory.parent != previous:
            raise ValueError('Services are running different release directories')
        previous = directory.parent
        unit = Path(output('systemctl', 'show', name, '-p', 'FragmentPath', '--value'))
        if unit != Path('/etc/systemd/system') / (name + '.service'):
            raise ValueError('Unexpected systemd unit')
        units[name] = unit.read_text()
    if not (DATA / 'policy.db').is_file() or not (DATA / 'ai.env').is_file():
        raise ValueError('Existing production data/configuration not found')
    release = SERVER_ROOT / 'weijianwei-releases' / revision
    backup = SERVER_ROOT / 'weijianwei-backups' / f'sync-{time.time_ns()}'
    backup.mkdir(mode=0o700)
    print('Downloading complete source revision:', revision, flush=True)
    with urllib.request.urlopen(f'https://codeload.github.com/clotiss/WeiJianwei/tar.gz/{revision}', timeout=90) as response:
        archive = response.read(32 * 1024 * 1024 + 1)
    if len(archive) > 32 * 1024 * 1024: raise ValueError('Archive download too large')
    staged = backup / 'staged-source'
    staged.mkdir()
    manifest = extract_source(archive, staged)
    if manifest['source_sha256'] != expected:
        raise ValueError('Full source digest does not match the local checkout; no services changed')
    manifest['revision'] = revision
    (staged / MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    if release.exists():
        actual = source_manifest(release, [p.relative_to(release).as_posix() for p in release.rglob('*') if p.is_file() and 'venv' not in p.relative_to(release).parts])
        if actual['source_sha256'] != expected: raise ValueError('Existing release has different files')
        shutil.rmtree(staged)
    else:
        staged.rename(release)
    # Reuse the proven environment only when its dependency declarations match.
    for name in ('requirements.txt', 'requirements-v2.txt'):
        if (release / 'backend' / name).read_bytes() != (previous / 'backend' / name).read_bytes():
            raise ValueError('Dependency declarations changed; prepare a new environment before cutover')
    venv = release / 'backend/venv'
    if not venv.exists(): venv.symlink_to((previous / 'backend/venv').resolve(), target_is_directory=True)
    python = venv / 'bin/python'
    env = dict(os.environ, POLICY_AI_CONFIG_FILE=str(DATA / 'ai.env'),
               POLICY_DATABASE_URL='sqlite:///' + str(DATA / 'policy.db'),
               POLICY_OBJECT_ROOT=str(DATA / 'objects'), POLICY_RELEASE_REVISION=revision,
               POLICY_SOURCE_SHA256=expected)
    run(python, '-c', "from policy_v2.settings import Settings; import os; s=Settings(_env_file=os.environ['POLICY_AI_CONFIG_FILE']); assert s.ai_concurrency == 10; assert s.wechat_app_id and s.wechat_secret", cwd=release / 'backend', env=env)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0)); port = listener.getsockname()[1]
    with (backup / 'preflight.log').open('w') as log:
        process = subprocess.Popen([str(python), '-m', 'uvicorn', 'policy_v2.app:app', '--host', '127.0.0.1', '--port', str(port)],
                                   cwd=release / 'backend', env=env, stdout=log, stderr=log)
        try: smoke(port, revision, expected)
        finally:
            process.terminate()
            try: process.wait(timeout=20)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
    for name, original in units.items():
        (backup / (name + '.service')).write_text(original)
        (backup / (name + '.new.service')).write_text(service_unit(original, previous, release, revision, expected))
    print('Full source and preflight checks passed; switching all three services.', flush=True)
    try:
        run('sudo', '-n', 'systemctl', 'stop', 'weijianwei-worker', 'weijianwei-summary')
        run('sudo', '-n', 'systemctl', 'stop', 'nhc-api')
        with sqlite3.connect(DATA / 'policy.db') as source, sqlite3.connect(backup / 'policy.db') as target:
            source.backup(target)
        for name in SERVICES:
            run('sudo', '-n', 'install', '-m', '644', backup / (name + '.new.service'), '/etc/systemd/system/' + name + '.service')
        run('sudo', '-n', 'systemctl', 'daemon-reload')
        run('sudo', '-n', 'systemctl', 'start', *SERVICES)
        total = smoke(8000, revision, expected)
        run('systemctl', 'is-active', *SERVICES)
        for name in SERVICES:
            if output('systemctl', 'show', name, '-p', 'WorkingDirectory', '--value') != str(release / 'backend'):
                raise RuntimeError('Service release directory mismatch')
        actual = source_manifest(release, [p.relative_to(release).as_posix() for p in release.rglob('*') if p.is_file() and 'venv' not in p.relative_to(release).parts])
        if actual['source_sha256'] != expected: raise RuntimeError('Post-deployment source mismatch')
    except Exception:
        run('sudo', '-n', 'systemctl', 'stop', *SERVICES)
        for name in SERVICES:
            run('sudo', '-n', 'install', '-m', '644', backup / (name + '.service'), '/etc/systemd/system/' + name + '.service')
        run('sudo', '-n', 'systemctl', 'daemon-reload')
        run('sudo', '-n', 'systemctl', 'start', *SERVICES)
        print('Cutover failed; all service definitions restored. Backup:', backup, flush=True)
        raise
    print(json.dumps({'revision': revision, 'source_sha256': expected, 'verified_files': len(manifest['files']),
                      'release': str(release), 'backup': str(backup), 'policies': total, 'status': 'synchronized'}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    local = sub.add_parser('fingerprint')
    local.add_argument('--root', type=Path, default=Path.cwd())
    remote = sub.add_parser('deploy')
    remote.add_argument('--revision', required=True)
    remote.add_argument('--source-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'fingerprint':
        manifest = local_manifest(args.root.resolve())
        print(json.dumps({key: value for key, value in manifest.items() if key != 'files'} | {'verified_files': len(manifest['files'])}))
    else: deploy(args.revision, args.source_sha256)


if __name__ == '__main__': main()
