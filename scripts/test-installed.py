#!/usr/bin/env python3
"""Validate the installed native runtime without changing active files or using real keys."""
import argparse
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import time
import uuid

from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path("/opt/desktop-commander-mcp")
HELPERS = Path("/usr/local/libexec/desktop-commander-mcp")
EXAMPLES = Path("/usr/local/share/desktop-commander-mcp")
RUNTIME_HOME = Path("/var/lib/desktop-commander-mcp/home")
SERVICE = "desktop-commander-mcp.service"
# Synthetic fixture only. The script never runs tunnel-client run or contacts OpenAI.
SECRET = "sk-" + "Z" * 40


def run(command, expected=0, env=None):
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True,
                            timeout=300, check=False, env=env)
    if SECRET in result.stdout + result.stderr:
        raise RuntimeError("A check disclosed synthetic secret content.")
    if result.returncode != expected:
        raise RuntimeError(f"A check returned {result.returncode}; expected {expected}.")
    return result.stdout.strip()


def properties(unit, *names):
    return dict(line.split("=", 1) for line in run(
        ["systemctl", "show", unit, *["--property=" + name for name in names]]
    ).splitlines() if "=" in line)


def state():
    return properties(SERVICE, "ActiveState", "UnitFileState")


def current_link():
    current = PREFIX / "current"
    return os.readlink(current) if current.is_symlink() else None


def wait_ready(home, unit):
    marker = home / "native-ready.json"
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if marker.is_file():
            return json.loads(marker.read_text())
        status = properties(unit, "ActiveState")
        if status.get("ActiveState") == "failed":
            break
        time.sleep(0.25)
    raise RuntimeError("The native stdio fixture did not become ready.")


def cgroup_pids(unit):
    group = properties(unit, "ControlGroup").get("ControlGroup", "")
    if not group.startswith("/system.slice/"):
        raise RuntimeError("The test daemon is outside its systemd service cgroup.")
    path = Path("/sys/fs/cgroup") / group.lstrip("/")
    return {int(pid) for source in path.rglob("cgroup.procs")
            for pid in source.read_text().split()}


def live(pid):
    try:
        # A zombie has exited; it cannot keep a daemon/tool running.
        return Path(f"/proc/{pid}/stat").read_text().split(") ", 1)[1][0] != "Z"
    except FileNotFoundError:
        return False


def wait_exited(pids):
    deadline = time.monotonic() + 5
    while any(live(pid) for pid in pids) and time.monotonic() < deadline:
        time.sleep(0.1)
    if any(live(pid) for pid in pids):
        raise RuntimeError("A stopped/replaced systemd child is still running.")


def test_stdio(release, home, account):
    unit = "dcmcp-native-test-" + uuid.uuid4().hex + ".service"
    # Use the installed unit's lifecycle settings with an SDK test supervisor.
    config = properties(SERVICE, "KillMode", "Restart", "RestartUSec", "TimeoutStopUSec")
    if config.get("KillMode") != "control-group" or config.get("Restart") != "always":
        raise RuntimeError("The installed unit has unexpected process lifecycle settings.")
    command = [
        "sudo", "-n", "systemd-run", "--quiet", "--unit=" + unit,
        "--property=User=" + account.pw_name, "--property=Group=" + str(account.pw_gid),
        "--property=WorkingDirectory=" + account.pw_dir,
        "--property=KillMode=" + config["KillMode"],
        "--property=Restart=" + config["Restart"], "--property=RestartSec=10",
        "--property=TimeoutStopSec=45", "--property=UMask=0077",
        "--property=PrivateNetwork=yes",  # Fixture only: prevent browser/flag downloads.
        "--setenv=HOME=" + str(home), str(release / "node/bin/node"),
        str(ROOT / "tests/native/mcp-client.mjs"), str(release), str(home),
        account.pw_name, str(account.pw_uid),
    ]
    try:
        run(command)
        first = wait_ready(home, unit)
        old_pids = cgroup_pids(unit)
        if (first["parent_pid"] not in old_pids or first["mcp_pid"] not in old_pids
                or len(old_pids) < 3):
            raise RuntimeError("The SDK, MCP and tool child are not in the same service cgroup.")
        print(f"PASS: native MCP initialize/tools/list ({first['tools_count']} tools), "
              "get_config, list_directory and existing user/sudo.", flush=True)
        (home / "native-ready.json").unlink()
        run(["sudo", "-n", "systemctl", "restart", unit])
        second = wait_ready(home, unit)
        wait_exited(old_pids)
        new_pids = cgroup_pids(unit)
        if second["parent_pid"] == first["parent_pid"] or old_pids & new_pids:
            raise RuntimeError("The native restart overlapped old/new processes.")
        print("PASS: systemd restart replaces the stdio supervisor and all children.", flush=True)
        run(["sudo", "-n", "systemctl", "stop", unit])
        wait_exited(new_pids)
        print("PASS: systemd stop terminates MCP and long-lived tool children.", flush=True)
    finally:
        subprocess.run(["sudo", "-n", "systemctl", "stop", unit],
                       capture_output=True, check=False)
        subprocess.run(["sudo", "-n", "systemctl", "reset-failed", unit],
                       capture_output=True, check=False)


def test_missing_configuration(account, release):
    paths = (RUNTIME_HOME / ".config/desktop-commander-mcp/tunnel.yaml",
             RUNTIME_HOME / ".config/desktop-commander-mcp/runtime.key",
             Path(account.pw_dir) / ".claude-server-commander/config.json")
    if any(path.exists() or path.is_symlink() for path in paths) or current_link() is not None:
        print("SKIP: production rejection checks; operator configuration/selection exists.")
        return
    if state() != {"ActiveState": "inactive", "UnitFileState": "disabled"}:
        print("SKIP: production rejection checks; unit is not inactive/disabled.")
        return
    env = os.environ.copy()
    env["HOME"] = str(RUNTIME_HOME)
    run(["/usr/bin/python3", str(HELPERS / "preflight.py"), "--user", account.pw_name,
         "--release", str(release)], expected=78, env=env)
    with tempfile.TemporaryDirectory(prefix="dcmcp-playbook-") as directory:
        inventory = Path(directory) / "hosts.yml"
        inventory.write_text(
            "all:\n  children:\n    mcp_servers:\n      hosts:\n        localhost:\n"
            "          ansible_connection: local\n"
            "          dcmcp_user: " + account.pw_name + "\n")
        for playbook in ("preflight", "activate"):
            run(["ansible-playbook", "-i", str(inventory),
                 f"playbooks/{playbook}.yml"], expected=2)
        unsupported = Path(directory) / "unsupported.yml"
        unsupported.write_text(
            "---\n- name: Check unsupported release rejection\n  hosts: mcp_servers\n"
            "  gather_facts: false\n  vars:\n    ansible_facts:\n"
            "      distribution: Ubuntu\n      distribution_version: '24.04'\n"
            "      architecture: x86_64\n      service_mgr: systemd\n"
            "      virtualization_type: kvm\n  tasks:\n"
            "    - name: Validate native host context\n      ansible.builtin.include_role:\n"
            "        name: dcmcp\n        tasks_from: context\n")
        rejected = run(["ansible-playbook", "-i", str(inventory), str(unsupported)], expected=2)
        if "changed=0" not in rejected or "Supported native hosts" not in rejected:
            raise RuntimeError("Ubuntu 24.04 was not rejected before any change.")
        print("PASS: Ansible rejects synthetic Ubuntu 24.04 facts before any change.", flush=True)
    if state() != {"ActiveState": "inactive", "UnitFileState": "disabled"} or current_link():
        raise RuntimeError("Rejected activation changed production selection or state.")
    # Exercise the real installed launcher/unit: no config means no network or MCP spawn.
    run(["sudo", "-n", "systemctl", "start", SERVICE])
    deadline = time.monotonic() + 5
    status = {}
    while time.monotonic() < deadline:
        status = properties(SERVICE, "ActiveState", "ExecMainStatus", "NRestarts")
        if status.get("ActiveState") == "failed":
            break
        time.sleep(0.1)
    try:
        if status != {"ActiveState": "failed", "ExecMainStatus": "78", "NRestarts": "0"}:
            raise RuntimeError("The real unit did not reject missing config without a restart loop.")
    finally:
        run(["sudo", "-n", "systemctl", "stop", SERVICE])
        run(["sudo", "-n", "systemctl", "reset-failed", SERVICE])
    print("PASS: installed CLI, Ansible preflight/activation and systemd refuse missing config; "
          "no selector, enablement or restart loop.", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true",
                        help="Test this authorized native Ubuntu 26.04 host; requires existing sudo")
    parser.add_argument("--release-id", help="An installed release; required if more than one exists")
    args = parser.parse_args()
    if not args.local:
        parser.error("--local is required to run native host/service checks")
    require_native_host()
    account = pwd.getpwuid(os.geteuid())
    if account.pw_uid == 0:
        parser.error("run as the existing non-root runtime user, using its existing sudo rights")
    run(["sudo", "-n", "true"])
    releases = [path for path in (PREFIX / "releases").iterdir()
                if not path.name.startswith(".") and (path / "release.json").is_file()]
    if args.release_id:
        releases = [path for path in releases if path.name == args.release_id]
    if len(releases) != 1:
        parser.error("select exactly one completed release using --release-id")
    release = releases[0]
    before_state, before_link = state(), current_link()
    unit = properties(SERVICE, "User", "WorkingDirectory", "Environment",
                      "Requires", "Wants", "After", "PartOf")
    if unit.get("User") != account.pw_name or ("HOME=" + str(RUNTIME_HOME)) not in unit["Environment"]:
        raise RuntimeError("The installed daemon account or process HOME is incorrect.")
    dependencies = " ".join(unit.get(key, "") for key in ("Requires", "Wants", "After", "PartOf"))
    if "docker" in dependencies.lower() or "podman" in dependencies.lower():
        raise RuntimeError("The native daemon depends on a container runtime.")
    test_missing_configuration(account, release)
    old_umask = os.umask(0o077)
    try:
        with tempfile.TemporaryDirectory(prefix="dcmcp-native-") as directory:
            home = Path(directory)
            account_home = home / "account-home"
            tunnel = home / ".config/desktop-commander-mcp/tunnel.yaml"
            key = tunnel.parent / "runtime.key"
            desktop = account_home / ".claude-server-commander/config.json"
            tunnel.parent.mkdir(parents=True, mode=0o700)
            desktop.parent.mkdir(mode=0o700)
            data = (EXAMPLES / "tunnel.yaml.example").read_text().replace(
                "REPLACE_WITH_PROVISIONED_TUNNEL_ID", "tunnel_" + "e" * 32).replace(
                str(RUNTIME_HOME), str(home))
            fixtures = {tunnel: data, key: SECRET + "\n",
                        desktop: (EXAMPLES / "desktop-commander.json.example").read_text()}
            env = os.environ.copy()
            env["HOME"] = str(home)
            command = ["/usr/bin/python3", str(HELPERS / "preflight.py"), "--user", account.pw_name,
                       "--home", str(home), "--account-home", str(account_home),
                        "--workdir", account.pw_dir,
                       "--release", str(release), "--fingerprint"]
            run(command, expected=78, env=env)
            for path, content in fixtures.items():
                path.write_text(content)
                path.chmod(0o600)
            first = run(command, env=env)
            if len(first) != 64 or first != run(command, env=env):
                raise RuntimeError("Native installed preflight is not stable.")
            print("PASS: real Node/npm/sharp/esbuild/SDK/ripgrep/tunnel probes and offline fingerprint.",
                  flush=True)
            for path, content, mode, label in [
                (tunnel, "api_key: [" + SECRET, 0o600, "malformed YAML"),
                (key, "REPLACE_WITH_RUNTIME_KEY", 0o600, "placeholder key"),
                (key, "sk-admin-" + "Z" * 40, 0o600, "administrative key"),
                (key, SECRET + "\n", 0o644, "public key permissions"),
                (desktop, '{"x":1,}', 0o600, "invalid strict JSON"),
            ]:
                path.write_text(content)
                path.chmod(mode)
                run(command, expected=78, env=env)
                print("PASS: installed preflight rejects " + label + ".", flush=True)
                path.write_text(fixtures[path])
                path.chmod(0o600)
            (home / "native-test-marker").write_text("isolated native MCP fixture\n")
            test_stdio(release, home, account)
    finally:
        os.umask(old_umask)
    if state() != before_state or current_link() != before_link:
        raise RuntimeError("Native checks changed production activation or selection.")
    print("Native installed checks passed; production configs/selection/state preserved. "
          "No authenticated OpenAI tunnel was started.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
