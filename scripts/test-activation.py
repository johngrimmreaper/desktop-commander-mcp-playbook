#!/usr/bin/env python3
"""Run real post-preflight activation tasks against private, local systemd fixtures."""
import copy
import hashlib
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import pwd
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import yaml

from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]
PREFIX = Path("/opt/desktop-commander-mcp")
HELPERS = Path("/usr/local/libexec/desktop-commander-mcp")
HOME = Path("/")
SERVICE = ""
SECRET = "sk-" + "Z" * 40


def run(command, expected=0, env=None):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=180, check=False)
    if SECRET in result.stdout + result.stderr:
        raise RuntimeError("A check disclosed the synthetic fixture key.")
    if result.returncode != expected:
        raise RuntimeError(f"Check returned {result.returncode}, expected {expected}.\n"
                           + result.stdout + result.stderr)
    return result


def properties(unit):
    result = run(["systemctl", "show", unit, "-p", "ActiveState", "-p", "UnitFileState",
                  "-p", "MainPID", "-p", "InvocationID"]).stdout
    return dict(line.split("=", 1) for line in result.splitlines() if "=" in line)


def production_snapshot():
    paths = [HOME / ".config/desktop-commander-mcp/tunnel.yaml",
             HOME / ".config/desktop-commander-mcp/runtime.key",
             Path(pwd.getpwuid(os.getuid()).pw_dir) / ".claude-server-commander/config.json"]
    files = {}
    for path in paths:
        if not path.exists():
            files[str(path)] = None
            continue
        data = path.read_bytes()
        if path.name == "config.json":
            # A live Desktop Commander writes usage counters asynchronously.
            # Compare its settings and permissions, not those counters.
            config = json.loads(data)
            config.pop("usageStats", None)
            data = json.dumps(config, sort_keys=True).encode()
        files[str(path)] = (hashlib.sha256(data).hexdigest(),
                            path.stat().st_mode, path.stat().st_uid)
    current = PREFIX / "instances" / pwd.getpwuid(os.getuid()).pw_name / "current"
    return properties(SERVICE), files, os.readlink(current) if current.is_symlink() else None


def wait_failed(unit):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if properties(unit)["ActiveState"] == "failed":
            return
        time.sleep(0.1)
    raise RuntimeError("The intentional failure fixture did not exit.")


def main():
    global HELPERS, HOME, SERVICE
    require_native_host()
    account = pwd.getpwuid(os.geteuid())
    if account.pw_uid == 0:
        raise RuntimeError("Run this check as the existing non-root runtime user.")
    HELPERS = HELPERS / account.pw_name
    HOME = Path(account.pw_dir)
    SERVICE = f"desktop-commander-mcp@{account.pw_name}.service"
    run(["sudo", "-n", "true"])
    before = production_snapshot()
    defaults = yaml.safe_load((ROOT / "roles/dcmcp/defaults/main.yml").read_text())
    release_id = (f"dc-{defaults['dcmcp_desktop_version']}-"
                  f"{defaults['dcmcp_desktop_revision'][:12]}-"
                  f"node-{defaults['dcmcp_node_version']}-"
                  f"tunnel-{defaults['dcmcp_tunnel_version']}-{os.uname().machine}")
    release = PREFIX / "releases" / release_id
    if not (release / "release.json").is_file():
        raise RuntimeError("Target pinned release is not installed")
    manifest = (release / "release.json").read_bytes()
    unit = "dcmcp-activation-test-" + uuid.uuid4().hex + ".service"
    unit_file = Path("/etc/systemd/system") / unit
    original_umask = os.umask(0o077)
    temporary = tempfile.mkdtemp(prefix="dcmcp-activation-test-")
    root = Path(temporary)
    env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / "ansible.cfg"),
               PYTHONDONTWRITEBYTECODE="1")
    unrelated = None
    try:
        home = root / "tunnel-home"
        account_home = root / "account-home"
        tunnel = home / ".config/desktop-commander-mcp/tunnel.yaml"
        desktop = account_home / ".claude-server-commander/config.json"
        tunnel.parent.mkdir(parents=True, mode=0o700)
        desktop.parent.mkdir(mode=0o700)
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            address = "127.0.0.1:" + str(listener.getsockname()[1])
        cfg = yaml.safe_load((Path("/usr/local/share/desktop-commander-mcp") / account.pw_name /
                              "tunnel.yaml.example").read_text())
        cfg["control_plane"]["tunnel_id"] = "tunnel_" + "e" * 32
        cfg["control_plane"]["api_key"] = "file:" + str(tunnel.parent / "runtime.key")
        cfg["health"]["listen_addr"] = address
        tunnel.write_text(yaml.safe_dump(cfg))
        (tunnel.parent / "runtime.key").write_text(SECRET + "\n")
        desktop.write_text((Path("/usr/local/share/desktop-commander-mcp") / account.pw_name /
                            "desktop-commander.json.example").read_text())
        for path in (tunnel, tunnel.parent / "runtime.key", desktop):
            path.chmod(0o600)
        # Validate the real installed candidate first, without contacting OpenAI.
        run(["/usr/bin/python3", str(HELPERS / "preflight.py"), "--user", account.pw_name,
             "--home", str(home), "--account-home", str(account_home),
             "--release", str(release)], env=dict(env, HOME=str(home)))
        isolated = root / "installation"
        candidate = isolated / "releases" / release.name
        run(["sudo", "-n", "mkdir", "-p", str(candidate)])
        instance = isolated / "instances" / account.pw_name
        run(["sudo", "-n", "mkdir", "-p", str(instance)])
        # sudo can inherit this test's private umask. Keep non-secret root-owned
        # fixture directories traversable so selector assertions inspect real links.
        run(["sudo", "-n", "chmod", "0755", str(isolated), str(isolated / "releases"),
             str(candidate), str(isolated / "instances"), str(instance)])
        saved = root / "release.json"
        saved.write_bytes(manifest)
        run(["sudo", "-n", "install", "-m", "0644", str(saved), str(candidate / "release.json")])
        selector = root / "select-release.py"
        selector.write_text((ROOT / "roles/dcmcp/files/select-release.py").read_text().replace(
            'PREFIX = Path("/opt/desktop-commander-mcp")', "PREFIX = Path(" + repr(str(isolated)) + ")"))
        stamp = root / "activation.sha256"
        source = (ROOT / "roles/dcmcp/tasks/activate.yml").read_text().replace(
            "^/opt/desktop-commander-mcp/releases/", "^" + str(isolated) + "/releases/")
        # Only fixture paths, unit name and retry duration change. The candidate
        # preflight above replaces its fixed-production-path role import.
        tasks = yaml.safe_load(source)[1:]
        for task in tasks:
            if task.get("register") == "dcmcp_fingerprint":
                argv = task["ansible.builtin.command"]["argv"]
                argv[-2] = str(release)
                argv += ["--home", str(home), "--account-home", str(account_home)]
            for child in task.get("block", []) + task.get("rescue", []):
                if child.get("name") in ("Atomically select the validated release",
                                         "Restore the previous release selector if one existed"):
                    child["ansible.builtin.command"]["argv"][1] = str(selector)
                if child.get("register") == "dcmcp_readiness":
                    child["retries"] = 1
                    child["delay"] = 0
        settings = {"dcmcp_prefix": str(isolated), "dcmcp_helpers": str(HELPERS),
                    "dcmcp_current": str(instance / "current"),
                    "dcmcp_activation_stamp": str(stamp),
                    "dcmcp_target_release": release.name, "dcmcp_user": account.pw_name,
                    "dcmcp_workdir": account.pw_dir, "dcmcp_home": str(home),
                    "dcmcp_service": unit, "dcmcp_restart": False,
                    "dcmcp_tunnel_config": str(tunnel)}

        def activate(expected=0, force=False, subset=None):
            variables = dict(settings, dcmcp_restart=force)
            play = [{"name": "Native activation regression", "hosts": "localhost",
                     "become": True, "gather_facts": False, "vars": variables,
                     "tasks": copy.deepcopy(subset if subset is not None else tasks)}]
            playbook = root / "activate.yml"
            playbook.write_text(yaml.safe_dump(play, sort_keys=False))
            return run(["ansible-playbook", "-i", "localhost,", "-c", "local", str(playbook)],
                       expected=expected, env=env)

        def install_unit(option=""):
            fixture = ROOT / "tests/native/activation-service.py"
            text = ("[Unit]\nDescription=Isolated native activation fixture\n"
                    "[Service]\nType=simple\nUser=" + account.pw_name
                    + "\nGroup=" + str(account.pw_gid) + "\nWorkingDirectory=" + str(home)
                    + "\nExecStart=/usr/bin/python3 " + str(fixture) + " --listen-addr "
                    + address + (" " + option if option else "")
                    + "\nRestart=always\nRestartSec=10\nRestartPreventExitStatus=78\n"
                    "KillMode=control-group\n[Install]\nWantedBy=multi-user.target\n")
            unit_source = root / "fixture.service"
            unit_source.write_text(text)
            run(["sudo", "-n", "install", "-m", "0644", str(unit_source), str(unit_file)])

        install_unit()
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        activate()
        first = properties(unit)
        if (first["ActiveState"] != "active" or int(first["MainPID"]) <= 0
                or not stamp.is_file() or (instance / "current").resolve() != candidate):
            raise RuntimeError("First activation did not start and record the private fixture.")
        print("PASS: a fresh disabled unit activates after daemon-reload.", flush=True)
        second = activate()
        if "changed=0" not in second.stdout or properties(unit) != first:
            raise RuntimeError("Unchanged activation restarted or changed the service.")
        print("PASS: unchanged activation preserves the PID and invocation with changed=0.", flush=True)
        run(["sudo", "-n", "systemctl", "stop", unit])
        install_unit("--fail")
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "systemctl", "start", unit])
        wait_failed(unit)
        reset_tasks = next(task["block"] for task in tasks if "block" in task)
        reset_tasks = [task for task in reset_tasks if task.get("register") == "dcmcp_start_state"
                       or task.get("name") in ("Require a loadable installed unit before starting",
                                              "Clear a retained start-rate or configuration failure")]
        activate(subset=reset_tasks)
        if properties(unit)["ActiveState"] == "failed":
            raise RuntimeError("The retained failed state was not reset.")
        print("PASS: a retained failed unit is reset without ignoring systemctl errors.", flush=True)
        install_unit()
        activate(force=True)
        print("PASS: recovery activates after a prior configuration failure.", flush=True)
        run(["sudo", "-n", "systemctl", "stop", unit])
        run(["sudo", "-n", "systemctl", "disable", unit])
        run(["sudo", "-n", "rm", "-f", str(stamp), str(instance / "current")])

        class UnrelatedHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"ready\\n")
            def log_message(self, *_args):
                pass

        host, port = address.split(":")
        unrelated = ThreadingHTTPServer((host, int(port)), UnrelatedHandler)
        threading.Thread(target=unrelated.serve_forever, daemon=True).start()
        for option, label in (("--fail", "failed unit"), ("--idle", "running unit without its own listener")):
            install_unit(option)
            activate(expected=2)
            status = properties(unit)
            if (stamp.exists() or (instance / "current").exists()
                    or (instance / "current").is_symlink()
                    or status["UnitFileState"] != "disabled" or int(status["MainPID"]) != 0):
                raise RuntimeError("Failed first activation recorded success or did not restore state.")
            print(f"PASS: unrelated HTTP 200 cannot hide a {label}; first activation is undone.",
                  flush=True)

        # A failed replacement restores its old selector/enablement and stays stopped.
        previous = isolated / "releases/previous-fixture"
        run(["sudo", "-n", "mkdir", "-m", "0755", str(previous)])
        run(["sudo", "-n", "install", "-m", "0644", str(saved), str(previous / "release.json")])
        run(["sudo", "-n", "/usr/bin/python3", str(selector), previous.name, account.pw_name])
        # A failed unit can still be enabled; rollback must preserve that policy.
        install_unit("--fail")
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "systemctl", "start", unit])
        wait_failed(unit)
        run(["sudo", "-n", "systemctl", "enable", unit])
        if (instance / "current").resolve() != previous:
            raise RuntimeError("The previous selector fixture is not readable.")
        failure = activate(expected=2, force=True)
        status = properties(unit)
        if ((instance / "current").resolve() != previous or status["UnitFileState"] != "enabled"
                or int(status["MainPID"]) != 0 or stamp.exists()):
            raise RuntimeError("Failed replacement did not restore its prior stopped selection: "
                               + repr({"selector": str((instance / "current").resolve()),
                                       "expected_selector": str(previous), "state": status,
                                       "stamp_exists": stamp.exists()})
                               + "\n" + failure.stdout + failure.stderr)
        print("PASS: failed replacement preserves a failed-but-enabled prior unit and selector.",
              flush=True)
        unrelated.shutdown()
        unrelated.server_close()
        unrelated = None
        install_unit()
        activate()
        print("PASS: a valid replacement recovers after failed readiness.", flush=True)

        # Preserve the success stamp while a wrong listener answers for an idle service.
        # This exercises the unchanged-input branch, not just the replacement branch.
        run(["sudo", "-n", "systemctl", "stop", unit])
        unrelated = ThreadingHTTPServer((host, int(port)), UnrelatedHandler)
        threading.Thread(target=unrelated.serve_forever, daemon=True).start()
        install_unit("--idle")
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "systemctl", "start", unit])
        activate(expected=2)
        if properties(unit)["ActiveState"] != "active":
            raise RuntimeError("Unchanged readiness unexpectedly mutated the running fixture.")
        print("PASS: unchanged activation rejects an unrelated health listener.", flush=True)
    finally:
        if unrelated:
            unrelated.shutdown()
            unrelated.server_close()
        for action in ("stop", "disable", "reset-failed"):
            subprocess.run(["sudo", "-n", "systemctl", action, unit], capture_output=True,
                           text=True, check=False)
        run(["sudo", "-n", "rm", "-f", "--", str(unit_file)])
        run(["sudo", "-n", "systemctl", "daemon-reload"])
        run(["sudo", "-n", "rm", "-rf", "--", str(root)])
        os.umask(original_umask)
        if production_snapshot() != before or unit_file.exists():
            raise RuntimeError("Native regression cleanup changed production state.")
        print("PASS: temporary unit and fixtures removed; production state preserved.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
