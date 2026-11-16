#!/usr/bin/env python3
"""Verify a live, installed native release without changing service or secrets."""
import argparse
import json
import os
from pathlib import Path
import pwd
import stat
import subprocess
import sys

import yaml

from doctor import configure_user, diagnose, selected_release
from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path('/opt/desktop-commander-mcp')
PREFLIGHT = Path('/usr/local/libexec/desktop-commander-mcp/preflight.py')
RUNTIME_HOME = '/'
SERVICE = ''


def expected_release(defaults, architecture):
    return (f"dc-v2-{defaults['dcmcp_desktop_version']}-"
            f"{defaults['dcmcp_desktop_revision'][:12]}-"
            f"node-{defaults['dcmcp_node_version']}-"
            f"openai-tunnel-{defaults['dcmcp_tunnel_version']}-{architecture}")


def expected_manifest(defaults, architecture):
    return {
        'schema': 2, 'transport': 'openai_tunnel', 'architecture': architecture,
        'desktop_version': defaults['dcmcp_desktop_version'],
        'desktop_revision': defaults['dcmcp_desktop_revision'],
        'lock_blob': defaults['dcmcp_lock_blob'],
        'node_version': defaults['dcmcp_node_version'],
        'node_sha256': defaults['dcmcp_node_checksums'][architecture],
        'tunnel_version': defaults['dcmcp_tunnel_version'],
        'tunnel_sha256': defaults['dcmcp_tunnel_checksums'][architecture],
    }


def trusted_root_regular(path):
    try:
        info = path.lstat()
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022


def preflight_passes(user, release, workdir, release_only):
    if not trusted_root_regular(PREFLIGHT):
        return False
    command = ['/usr/bin/python3', str(PREFLIGHT), '--user', user,
               '--release', str(release), '--workdir', workdir]
    if release_only:
        command.append('--release-only')
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False,
                                timeout=20, env={**os.environ, 'HOME': RUNTIME_HOME})
        return result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def audit():
    """Only fixed checks are returned; never return config or external command output."""
    checks = {}
    defaults = yaml.safe_load((ROOT / 'roles/dcmcp/defaults/main.yml').read_text())
    arch = os.uname().machine
    identifier = expected_release(defaults, arch)
    release = PREFIX / 'releases' / identifier
    checks['selected_expected_release'] = selected_release() == identifier
    try:
        manifest = json.loads((release / 'release.json').read_text())
        checks['manifest_matches_pins'] = (manifest == expected_manifest(defaults, arch)
                                            and trusted_root_regular(release / 'release.json'))
    except (OSError, ValueError, KeyError):
        checks['manifest_matches_pins'] = False
    state = subprocess.run(['systemctl', 'show', SERVICE,
                            '-p', 'User', '-p', 'WorkingDirectory', '--no-pager'],
                           capture_output=True, text=True, timeout=5, check=False)
    attributes = dict(line.split('=', 1) for line in state.stdout.splitlines() if '=' in line)
    account = pwd.getpwuid(os.geteuid()).pw_name
    workdir = attributes.get('WorkingDirectory', '')
    checks['runtime_identity'] = (state.returncode == 0 and attributes.get('User') == account
                                  and os.geteuid() > 0 and workdir.startswith('/'))
    checks['immutable_release_offline'] = (checks['selected_expected_release']
                                           and checks['manifest_matches_pins']
                                           and checks['runtime_identity']
                                           and preflight_passes(account, release, workdir, True))
    checks['active_config_offline'] = (checks['immutable_release_offline']
                                      and preflight_passes(account, release, workdir, False))
    runtime = diagnose()
    checks['managed_runtime_healthy'] = all(value for key, value in runtime.items()
                                            if key != 'selinux')
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--local', action='store_true', help='Explicitly audit this native host')
    parser.add_argument('--json', action='store_true', help='Only boolean status fields')
    args = parser.parse_args()
    if not args.local:
        parser.error('--local is required to select the installed host explicitly')
    require_native_host(allow_rpm=True, allow_arch=True)
    global PREFLIGHT, RUNTIME_HOME, SERVICE
    account = pwd.getpwuid(os.geteuid())
    configure_user(account.pw_name)
    PREFLIGHT = Path(f'/usr/local/libexec/desktop-commander-mcp/{account.pw_name}/preflight.py')
    RUNTIME_HOME = account.pw_dir
    SERVICE = f'desktop-commander-mcp@{account.pw_name}.service'
    try:
        checks = audit()
    except (OSError, KeyError, ValueError, subprocess.TimeoutExpired):
        print('Read-only audit failed: installed facts unavailable (no secrets shown).',
              file=sys.stderr)
        return 1
    passed = all(checks.values())
    if args.json:
        print(json.dumps({'passed': passed, 'checks': checks}, indent=2, sort_keys=True))
    else:
        for name, ok in checks.items():
            print(f'{name}: {"PASS" if ok else "FAIL"}')
        print('Overall: ' + ('PASS' if passed else 'FAIL'))
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
