import importlib.util
import io
from pathlib import Path
import tarfile
import sqlite3
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('release_sync', ROOT / 'deploy/sync-release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def archive(files, link=None):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w:gz') as tar:
        for name, contents in files.items():
            member = tarfile.TarInfo(name)
            member.size = len(contents)
            tar.addfile(member, io.BytesIO(contents))
        if link:
            member = tarfile.TarInfo('source/link')
            member.type = tarfile.SYMTYPE
            member.linkname = link
            tar.addfile(member)
    return stream.getvalue()


def test_same_local_and_server_source_digest_without_data_or_private_settings(tmp_path):
    files = {'backend/main.py': b'print("api")', 'miniprogram/app.js': b'App({})',
             'miniprogram/project.config.json': b'{"appid":"test"}',
             'backend/nhc_policy.db': b'old database', 'miniprogram/project.private.config.json': b'personal',
             '.env': b'private configuration'}
    local = tmp_path / 'local'
    for name, contents in files.items():
        path = local / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)
    expected = release.source_manifest(local, files)
    server = tmp_path / 'server'
    actual = release.extract_source(archive({'source/' + name: content for name, content in files.items()}), server)
    assert actual == expected
    assert len(actual['files']) == 3
    assert not (server / 'backend/nhc_policy.db').exists()
    assert not (server / '.env').exists()
    assert not (server / 'miniprogram/project.private.config.json').exists()
    (server / 'backend/main.py').write_text('changed')
    assert release.source_manifest(server, actual['files'])['source_sha256'] != expected['source_sha256']


@pytest.mark.parametrize('name', ['../escape.py', 'source/../../escape.py', '/absolute.py'])
def test_archive_path_escape_is_rejected(tmp_path, name):
    with pytest.raises(ValueError, match='Unsafe archive path'):
        release.extract_source(archive({name: b'code'}), tmp_path)


def test_archive_symlinks_are_rejected(tmp_path):
    with pytest.raises(ValueError, match='link or special file'):
        release.extract_source(archive({}, link='/etc/passwd'), tmp_path)


def test_ide_json_formatting_is_ignored_but_configuration_changes_are_detected(tmp_path):
    name = 'miniprogram/project.config.json'
    path = tmp_path / name
    path.parent.mkdir()
    path.write_text('{"appid":"test","setting":{"urlCheck":false}}')
    first = release.source_manifest(tmp_path, [name])
    path.write_text('{\n "setting": {"urlCheck": false},\n "appid": "test"\n}\n')
    assert release.source_manifest(tmp_path, [name]) == first
    path.write_text('{"appid":"different","setting":{"urlCheck":false}}')
    assert release.source_manifest(tmp_path, [name]) != first


def test_switch_preserves_service_configuration_and_replaces_release_metadata():
    old, new = Path('/releases/old'), Path('/releases/new')
    original = ('[Service]\nUser=ubuntu\nWorkingDirectory=/releases/old/backend\n'
        'Environment=POLICY_AI_CONFIG_FILE=/data/ai.env\nEnvironment=POLICY_RELEASE_REVISION=old\n'
        'Environment=POLICY_SOURCE_SHA256=old\n'
        'ExecStart=/releases/old/backend/venv/bin/python -m policy_v2.national_service summary --root /data\n'
        'TimeoutStopSec=120\nUMask=0077\n')
    changed = release.service_unit(original, old, new, 'a' * 40, 'b' * 64)
    assert '/releases/old' not in changed
    assert 'WorkingDirectory=/releases/new/backend' in changed
    assert 'Environment=POLICY_AI_CONFIG_FILE=/data/ai.env' in changed
    assert '--root /data\nTimeoutStopSec=120\nUMask=0077' in changed
    assert changed.count('Environment=POLICY_RELEASE_REVISION=') == 1
    assert changed.count('Environment=POLICY_SOURCE_SHA256=') == 1
    assert release.service_unit(changed, new, new, 'a' * 40, 'b' * 64) == changed


def test_health_reports_deployed_source_identity(monkeypatch):
    from policy_v2.app import health
    monkeypatch.setenv('POLICY_RELEASE_REVISION', 'a' * 40)
    monkeypatch.setenv('POLICY_SOURCE_SHA256', 'b' * 64)
    assert health()['revision'] == 'a' * 40
    assert health()['source_sha256'] == 'b' * 64


@pytest.mark.parametrize('fail_cutover', [False, True])
def test_full_deploy_and_rollback_keep_production_data_and_config(tmp_path, monkeypatch, fail_cutover):
    root = tmp_path / 'server'
    previous = root / 'weijianwei-releases/old'
    data = root / 'weijianwei-data/national-service'
    (previous / 'backend/venv/bin').mkdir(parents=True)
    data.mkdir(parents=True)
    (root / 'weijianwei-backups').mkdir()
    (data / 'ai.env').write_text('private test configuration')
    with sqlite3.connect(data / 'policy.db') as db:
        db.execute('create table sample(value text)')
        db.execute("insert into sample values ('production data')")
    files = {'backend/requirements.txt': b'dependency', 'backend/requirements-v2.txt': b'dependency-v2',
             'backend/main.py': b'print("new api")', 'miniprogram/app.js': b'App({})'}
    for name in ('requirements.txt', 'requirements-v2.txt'):
        (previous / 'backend' / name).write_bytes(files['backend/' + name])
    expected_dir = tmp_path / 'local'
    for name, content in files.items():
        target = expected_dir / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    digest = release.source_manifest(expected_dir, files)['source_sha256']
    revision = 'a' * 40
    units = {name: f'[Service]\nWorkingDirectory={previous}/backend\nExecStart={previous}/backend/venv/bin/python -m test\n'
             for name in release.SERVICES}
    originals = dict(units)
    original_read = Path.read_text
    def read(path, *args, **kwargs):
        if path.parent == Path('/etc/systemd/system'): return units[path.stem]
        return original_read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', read)
    def output(*args):
        name = args[2]
        if 'DropInPaths' in args: return ''
        if 'FragmentPath' in args: return '/etc/systemd/system/' + name + '.service'
        return next(line.split('=', 1)[1] for line in units[name].splitlines() if line.startswith('WorkingDirectory='))
    def run(*args, **kwargs):
        args = tuple(map(str, args))
        if 'install' in args: units[Path(args[-1]).stem] = Path(args[-2]).read_text()
        return SimpleNamespace(returncode=0)
    class Listener:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def bind(self, address): pass
        def getsockname(self): return ('127.0.0.1', 8123)
    monkeypatch.setattr(release, 'SERVER_ROOT', root)
    monkeypatch.setattr(release, 'DATA', data)
    monkeypatch.setattr(release, 'output', output)
    monkeypatch.setattr(release, 'run', run)
    monkeypatch.setattr(release.urllib.request, 'urlopen', lambda *a, **k: io.BytesIO(archive({'source/' + n: v for n, v in files.items()})))
    monkeypatch.setattr(release.socket, 'socket', Listener)
    monkeypatch.setattr(release.subprocess, 'Popen', lambda *a, **k: SimpleNamespace(terminate=lambda: None, wait=lambda **k: None))
    def smoke(port, sha, content_sha):
        assert sha == revision and content_sha == digest
        if port == 8000 and fail_cutover: raise RuntimeError('simulated verification failure')
        return 100
    monkeypatch.setattr(release, 'smoke', smoke)
    if fail_cutover:
        with pytest.raises(RuntimeError, match='simulated verification failure'):
            release.deploy(revision, digest)
        assert units == originals
    else:
        release.deploy(revision, digest)
        assert all(str(root / 'weijianwei-releases' / revision) in unit for unit in units.values())
        assert all('POLICY_SOURCE_SHA256=' + digest in unit for unit in units.values())
    assert (data / 'ai.env').read_text() == 'private test configuration'
    with sqlite3.connect(data / 'policy.db') as db:
        assert db.execute('select value from sample').fetchone()[0] == 'production data'
    assert list((root / 'weijianwei-backups').glob('*/policy.db'))
