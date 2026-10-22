#!/usr/bin/env python3
"""Reject a manifest-only damaged bundle and reuse a complete native bundle without configs."""
import hashlib
import json
import os
from pathlib import Path
import pwd
import subprocess
import tempfile
import uuid

import yaml

from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path("/opt/desktop-commander-mcp")


def run(command, expected=0, env=None):
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                            text=True, timeout=180, check=False)
    if result.returncode != expected:
        raise RuntimeError(f"Release check returned {result.returncode}; expected {expected}.\n"
                           + result.stdout + result.stderr)
    return result


def main():
    require_native_host()
    account = pwd.getpwuid(os.geteuid())
    if account.pw_uid == 0:
        raise RuntimeError("Run this check as the existing non-root runtime user.")
    run(["sudo", "-n", "true"])
    defaults = yaml.safe_load((ROOT / "roles/dcmcp/defaults/main.yml").read_text())
    release_id = (f"dc-{defaults['dcmcp_desktop_version']}-"
                  f"{defaults['dcmcp_desktop_revision'][:12]}-"
                  f"node-{defaults['dcmcp_node_version']}-"
                  f"tunnel-{defaults['dcmcp_tunnel_version']}-{os.uname().machine}")
    release = PREFIX / "releases" / release_id
    if not (release / "release.json").is_file():
        raise RuntimeError(f"The target pinned release is not staged: {release_id}")
    manifest_bytes = (release / "release.json").read_bytes()
    manifest = json.loads(manifest_bytes)
    damaged = PREFIX / "releases" / ("dcmcp-release-test-" + uuid.uuid4().hex)
    current = PREFIX / "current"
    before = os.readlink(current) if current.is_symlink() else None
    env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"),
               PYTHONDONTWRITEBYTECODE="1")
    original_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="dcmcp-release-test-") as temporary:
            root = Path(temporary)
            home = root / "empty-home"
            home.mkdir(mode=0o700)
            # No active key, tunnel YAML or Desktop Commander JSON exists here.
            run(["/usr/bin/python3", str(ROOT / "roles/dcmcp/files/preflight.py"),
                 "--release-only", "--release", str(release), "--user", account.pw_name,
                 "--home", str(home), "--workdir", account.pw_dir], env=dict(env, HOME=str(home)))
            print("PASS: actual release-only CLI succeeds without any active configuration.",
                  flush=True)
            saved = root / "release.json"
            saved.write_bytes(manifest_bytes)
            run(["sudo", "-n", "mkdir", "-m", "0755", str(damaged)])
            run(["sudo", "-n", "install", "-m", "0644", str(saved), str(damaged / "release.json")])

            def reuse(release_id, expected):
                variables = {
                    "ansible_facts": {"architecture": os.uname().machine},
                    "dcmcp_user": account.pw_name, "dcmcp_gid": account.pw_gid,
                    "dcmcp_uid": account.pw_uid, "dcmcp_home": str(home),
                    "dcmcp_workdir": account.pw_dir, "dcmcp_release_id": release_id,
                    "dcmcp_desktop_version": manifest["desktop_version"],
                    "dcmcp_desktop_revision": manifest["desktop_revision"],
                    "dcmcp_lock_blob": manifest["lock_blob"],
                    "dcmcp_node_version": manifest["node_version"],
                    "dcmcp_tunnel_version": manifest["tunnel_version"],
                    "dcmcp_node_checksums": {os.uname().machine: manifest["node_sha256"]},
                    "dcmcp_tunnel_checksums": {os.uname().machine: manifest["tunnel_sha256"]},
                }
                play = [{"name": "Native release reuse regression", "hosts": "localhost",
                         "become": True, "gather_facts": False, "vars": variables,
                         "tasks": [{"name": "Exercise the actual release role",
                                    "ansible.builtin.include_role":
                                        {"name": "dcmcp", "tasks_from": "release"}}]}]
                path = root / "reuse.yml"
                path.write_text(yaml.safe_dump(play, sort_keys=False))
                return run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(path)],
                           expected=expected, env=env)

            invalid = reuse(damaged.name, 2)
            if "A required executable is missing or not executable." not in invalid.stdout:
                raise RuntimeError("The damaged bundle failed for an unexpected reason.")
            if (hashlib.sha256((damaged / "release.json").read_bytes()).digest()
                    != hashlib.sha256(manifest_bytes).digest()
                    or list(damaged.iterdir()) != [damaged / "release.json"]):
                raise RuntimeError("Validation overwrote or repaired the immutable damaged bundle.")
            print("PASS: the real release role rejects a manifest-only bundle without overwriting it.",
                  flush=True)
            valid = reuse(release.name, 0)
            if "changed=0" not in valid.stdout:
                raise RuntimeError("Complete bundle reuse was not idempotent.")
            if list(home.iterdir()):
                raise RuntimeError("Release validation created active configuration.")
            print("PASS: complete bundle reuse reports changed=0 and creates no active files.",
                  flush=True)
    finally:
        run(["sudo", "-n", "rm", "-rf", "--", str(damaged)])
        os.umask(original_umask)
        after = os.readlink(current) if current.is_symlink() else None
        if before != after or damaged.exists():
            raise RuntimeError("Release regression cleanup changed the production selector.")
        print("PASS: damaged fixture removed; production selection preserved.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
