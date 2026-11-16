#!/usr/bin/env python3
"""Explicit install integration check; never activate, create keys, or copy active examples."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import subprocess
import sys
import tempfile

from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ""


def snapshot(paths):
    result = {}
    for path in paths:
        if path.exists():
            info = path.stat()
            data = path.read_bytes()
            if path.name == "config.json":
                # The running MCP updates its own usage counters asynchronously;
                # install must preserve operator settings, not freeze those counters.
                document = json.loads(data)
                document.pop("usageStats", None)
                data = json.dumps(document, sort_keys=True).encode()
            result[str(path)] = (hashlib.sha256(data).hexdigest(),
                                 info.st_mode, info.st_uid, info.st_gid)
        else:
            result[str(path)] = None
    return result


def systemctl(*args):
    result = subprocess.run(["systemctl", *args, SERVICE], capture_output=True,
                            text=True, check=False)
    return result.stdout.strip()


def main():
    global SERVICE
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true",
                        help="Install on this authorized native Ubuntu 26.04 host as its EXISTING user")
    parser.add_argument("--runtime-user",
                        help="Existing non-root runtime account; explicit when the controller is root")
    args = parser.parse_args()
    if not args.local:
        parser.error("--local is required: this integration test installs packages and a disabled unit")
    require_native_host()
    if os.getuid() == 0 and not args.runtime_user:
        parser.error("a root controller must explicitly select an existing --runtime-user")
    try:
        account = (pwd.getpwnam(args.runtime_user) if args.runtime_user
                   else pwd.getpwuid(os.getuid()))
    except KeyError:
        parser.error("the runtime account must already exist; this test never creates users")
    if account.pw_uid == 0:
        parser.error("the existing runtime account must be non-root")
    SERVICE = f"desktop-commander-mcp@{account.pw_name}.service"
    home = Path(account.pw_dir)
    paths = (home / ".config/desktop-commander-mcp/tunnel.yaml",
             home / ".config/desktop-commander-mcp/runtime.key",
             Path(account.pw_dir) / ".claude-server-commander/config.json")
    before = snapshot(paths)
    current = Path(f"/opt/desktop-commander-mcp/instances/{account.pw_name}/current")
    before_link = os.readlink(current) if current.is_symlink() else None
    before_active = systemctl("is-active") == "active"
    before_enabled = systemctl("is-enabled") == "enabled"
    with tempfile.TemporaryDirectory(prefix="dcmcp-integration-") as directory:
        inventory = Path(directory) / "hosts.yml"
        # Use the runner/operator's existing account; the role never creates users.
        inventory.write_text(
            "all:\n  children:\n    mcp_servers:\n      hosts:\n        localhost:\n"
            "          ansible_connection: local\n"
            "          dcmcp_user: " + account.pw_name + "\n"
            "          dcmcp_transport: openai_tunnel\n")
        env = os.environ.copy()
        env["ANSIBLE_CONFIG"] = str(ROOT / "ansible.cfg")
        command = ["ansible-playbook", "-i", str(inventory), "playbooks/install.yml"]
        for attempt in (1, 2):
            print(f"Running install attempt {attempt} on the authorized native target.", flush=True)
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True,
                                    text=True, check=False)
            if result.returncode:
                print(result.stdout)
                print(result.stderr, file=sys.stderr)
                return result.returncode
            recaps = re.findall(r"^localhost\s+:.*$", result.stdout, re.MULTILINE)
            if recaps:
                print(f"Install attempt {attempt}: {recaps[-1]}", flush=True)
            if attempt == 2:
                changed = re.findall(r"\bchanged=(\d+)", result.stdout)
                if not changed or any(int(value) for value in changed):
                    print(result.stdout)
                    print("Idempotence failed: the second install changed resources.", file=sys.stderr)
                    return 1
    after_link = os.readlink(current) if current.is_symlink() else None
    if snapshot(paths) != before or after_link != before_link:
        print("Install modified active configuration or the current selector.", file=sys.stderr)
        return 1
    if (systemctl("is-active") == "active") != before_active:
        print("Install changed runtime activation state.", file=sys.stderr)
        return 1
    if (systemctl("is-enabled") == "enabled") != before_enabled:
        print("Install changed existing enablement or enabled a fresh unit.", file=sys.stderr)
        return 1
    print("Install integration passed: second run changed=0; configs, selector and state preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
