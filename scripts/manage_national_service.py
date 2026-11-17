"""Install/status/stop the local national API and collector as user launchd services."""
import argparse
import os
import plistlib
import subprocess
import sys
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'status', 'stop'])
    parser.add_argument('--root', type=Path, default=Path('.runtime/national-service'))
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This helper manages macOS launchd; use the documented service commands on Linux.')
    repo = Path(__file__).resolve().parent.parent
    root = args.root.resolve()
    target = Path.home() / 'Library/LaunchAgents'
    for role in ('api', 'worker', 'summary'):
        label = 'com.weijianwei.national-' + role
        service = f'gui/{os.getuid()}/{label}'
        destination = target / (label + '.plist')
        if args.command == 'status':
            subprocess.run(['launchctl', 'print', service], check=False)
            continue
        if args.command == 'stop':
            subprocess.run(['launchctl', 'bootout', service], check=False)
            # Remove only our definition; otherwise login would restart a stopped service.
            if destination.exists():
                content = plistlib.loads(destination.read_bytes())
                if content.get('Label') == label and str(root) in content.get('ProgramArguments', []):
                    destination.unlink()
            continue
        if not (root / 'service.json').is_file():
            parser.error('Import and enable the persistent dataset before installing services.')
        arguments = [str(repo / '.venv/bin/python'), '-m', 'policy_v2.national_service', role, '--root', str(root)]
        arguments += ['--port', '8892'] if role == 'api' else ['--workers', '6'] if role == 'worker' else []
        definition = {'Label': label, 'ProgramArguments': arguments, 'WorkingDirectory': '/private/tmp',
            'EnvironmentVariables': {'PYTHONPATH': str(repo / 'backend'), 'PYTHONUNBUFFERED': '1'},
            'RunAtLoad': True, 'KeepAlive': True, 'ThrottleInterval': 30,
            'StandardOutPath': '/private/tmp/weijianwei-national-' + role + '.log',
            'StandardErrorPath': '/private/tmp/weijianwei-national-' + role + '.log'}
        if destination.exists() and plistlib.loads(destination.read_bytes()).get('ProgramArguments') != arguments:
            parser.error('Existing launch agent points to another service root: ' + str(destination))
        target.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(plistlib.dumps(definition))
        running = subprocess.run(['launchctl', 'print', service], capture_output=True).returncode == 0
        if running:
            subprocess.run(['launchctl', 'bootout', service], check=True)
        # bootout returns before the old process has fully released its launchd job.
        for attempt in range(10):
            result = subprocess.run(['launchctl', 'bootstrap', f'gui/{os.getuid()}', str(destination)], capture_output=True, text=True)
            if result.returncode == 0:
                break
            if attempt == 9:
                raise RuntimeError(result.stderr.strip())
            time.sleep(2)
        print('Installed ' + label, flush=True)


if __name__ == '__main__':
    main()
