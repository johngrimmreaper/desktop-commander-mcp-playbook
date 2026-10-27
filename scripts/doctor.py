#!/usr/bin/env python3
"""Read-only, credential-safe diagnostics for an installed native MCP tunnel."""
import argparse
import json
from pathlib import Path
import pwd
import re
import stat
import subprocess
import sys

import yaml

READINESS = Path("/usr/local/libexec/desktop-commander-mcp/readiness.py")
PREFIX = Path("/opt/desktop-commander-mcp")
HOME = Path("/var/lib/desktop-commander-mcp/home")
SERVICE = "desktop-commander-mcp.service"
CONFIG_DIR = HOME / ".config/desktop-commander-mcp"


def probe(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def unit_state():
    output = probe(["systemctl", "show", SERVICE,
                    "--property=LoadState,ActiveState,UnitFileState,MainPID,User,ControlGroup",
                    "--no-pager"])
    if output is None:
        return None
    return dict(line.split("=", 1) for line in output.splitlines() if "=" in line)


def private_file(path, uid):
    try:
        info = path.lstat()
    except OSError:
        return False
    return (stat.S_ISREG(info.st_mode) and info.st_uid == uid
            and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1)


def selected_release(prefix=PREFIX):
    selector = prefix / "current"
    try:
        if not selector.is_symlink() or selector.lstat().st_uid != 0:
            return None
        release = selector.resolve(strict=True)
        base = (prefix / "releases").resolve(strict=True)
        if not release.is_relative_to(base) or release == base or not release.is_dir():
            return None
        return release.name
    except OSError:
        return None


def health_address(config):
    """Read only the loopback health address, never expose config/key contents."""
    try:
        document = yaml.safe_load(config.read_bytes())
        address = document["health"]["listen_addr"]
        match = re.fullmatch(r"127\.0\.0\.1:([1-9][0-9]{0,4})", address)
        if match and 1024 <= int(match.group(1)) <= 65535:
            return address
    except (OSError, TypeError, KeyError, ValueError, yaml.YAMLError):
        pass
    return None


def managed_readiness(address):
    """Use the installed checker: HTTP 200 from an unrelated process is not health."""
    try:
        info = READINESS.lstat()
        # The helper must have been installed by the role, not a symlink or
        # arbitrary user-writable script supplied from an untrusted directory.
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022:
            return False
    except OSError:
        return False
    return probe(["/usr/bin/python3", str(READINESS), "--unit", SERVICE,
                  "--listen-addr", address]) is not None


def child_running(group):
    if not group or not group.startswith("/system.slice/") or ".." in group:
        return False
    try:
        pids = (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.procs").read_text()
        for pid in pids.split():
            if not pid.isdigit():
                continue
            try:
                command = (Path("/proc") / pid / "cmdline").read_bytes().split(b"\0")
            except OSError:
                continue
            if any(b"/mcp/dist/index.js" in part for part in command):
                return True
    except OSError:
        return False
    return False


def diagnose():
    """Return a summary containing no secrets, config values or command output."""
    checks = {}
    unit = unit_state()
    checks["systemd"] = bool(unit and unit.get("LoadState") == "loaded"
                             and unit.get("ActiveState") == "active"
                             and unit.get("UnitFileState") == "enabled"
                             and unit.get("MainPID", "0").isdigit()
                             and int(unit["MainPID"]) > 0)
    checks["release"] = selected_release() is not None
    uid = None
    account_home = None
    if unit and unit.get("User"):
        try:
            account = pwd.getpwnam(unit["User"])
            uid = account.pw_uid
            account_home = Path(account.pw_dir)
        except KeyError:
            pass
    checks["runtime_user"] = uid is not None and uid > 0
    tunnel_files = (CONFIG_DIR / "tunnel.yaml", CONFIG_DIR / "runtime.key")
    desktop_config = (account_home / ".claude-server-commander/config.json"
                      if account_home is not None else None)
    checks["private_config"] = bool(
        uid is not None and desktop_config is not None
        and all(private_file(p, uid) for p in (*tunnel_files, desktop_config)))
    addr = health_address(tunnel_files[0]) if checks["private_config"] else None
    checks["loopback_health_config"] = addr is not None
    checks["readiness"] = bool(addr and managed_readiness(addr))
    checks["mcp_child"] = bool(unit and child_running(unit.get("ControlGroup", "")))
    selinux = probe(["getenforce"])
    # Ubuntu need not provide the getenforce command. RHEL must keep enforcing.
    checks["selinux"] = selinux if selinux in ("Enforcing", "Permissive", "Disabled") else "Not installed"
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Machine-readable secret-free results")
    args = parser.parse_args()
    checks = diagnose()
    good = all(value for key, value in checks.items() if key != "selinux")
    if args.json:
        print(json.dumps({"healthy": good, "checks": checks}, indent=2, sort_keys=True))
    else:
        for name, value in checks.items():
            print(f"{name}: {value if name == 'selinux' else ('OK' if value else 'FAIL')}")
        print("Overall: " + ("HEALTHY" if good else "UNHEALTHY"))
    return 0 if good else 1


if __name__ == "__main__":
    sys.exit(main())
