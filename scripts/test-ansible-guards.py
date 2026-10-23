#!/usr/bin/env python3
"""Exercise distro/systemd host guards with synthetic facts on native supported Linux."""
import copy
import os
import pwd
from pathlib import Path
import subprocess
import tempfile

import yaml

from check import tool_executable
from host import require_native_host

ROOT = Path(__file__).resolve().parents[1]


def main():
    require_native_host(allow_rpm=True, allow_arch=True)
    source = yaml.safe_load((ROOT / "roles/dcmcp/tasks/context.yml").read_text())
    # Test the actual early guard without reaching account or deployment tasks.
    boundary = next(i for i, task in enumerate(source)
                    if task["name"] == "Look up the existing runtime user")
    guard = source[:boundary]
    facts = {"distribution": "Ubuntu", "distribution_version": "26.04",
             "distribution_major_version": "26", "architecture": os.uname().machine,
             "service_mgr": "systemd",
             "virtualization_type": "kvm", "virtualization_tech_guest": ["kvm"]}
    variables = {"ansible_facts": facts, "dcmcp_user": pwd.getpwuid(os.geteuid()).pw_name,
                 "dcmcp_home": "/var/lib/desktop-commander-mcp/home",
                 "dcmcp_prefix": "/opt/desktop-commander-mcp",
                 "dcmcp_helpers": "/usr/local/libexec/desktop-commander-mcp",
                 "dcmcp_service": "desktop-commander-mcp.service"}
    cases = [("native VM", {}, None, True),
             ("native physical host", {"virtualization_type": "", "virtualization_tech_guest": []},
              None, True),
             ("Ubuntu 24.04", {"distribution_version": "24.04"}, None, False),
             ("RHEL 10.0", {"distribution": "RedHat", "distribution_version": "10.0",
                            "distribution_major_version": "10"}, None, True),
             ("RHEL 10.1", {"distribution": "RedHat", "distribution_version": "10.1",
                            "distribution_major_version": "10"}, None, True),
             ("RHEL 10.2", {"distribution": "RedHat", "distribution_version": "10.2",
                            "distribution_major_version": "10"}, None, True),
             ("RHEL 11", {"distribution": "RedHat", "distribution_version": "11.0",
                          "distribution_major_version": "11"}, None, False),
             ("RHEL 9", {"distribution": "RedHat", "distribution_version": "9.7",
                          "distribution_major_version": "9"}, None, False),
             ("Fedora 43", {"distribution": "Fedora", "distribution_version": "43",
                            "distribution_major_version": "43"}, None, True),
             ("Fedora 44", {"distribution": "Fedora", "distribution_version": "44",
                            "distribution_major_version": "44"}, None, True),
             ("Arch Linux rolling / Omarchy", {"distribution": "Archlinux",
                                                "distribution_version": "rolling",
                                                "distribution_major_version": ""}, None, True),
             ("Fedora 45 beta", {"distribution": "Fedora", "distribution_version": "45",
                                 "distribution_major_version": "45"}, None, False),
             ("Debian 13", {"distribution": "Debian", "distribution_version": "13",
                            "distribution_major_version": "13"}, None, False),
             ("unknown container", {"virtualization_type": "future-container",
                                    "virtualization_tech_guest": ["container"]}, None, False)]
    cases.extend([
        ("missing runtime account", {}, None, False),
        ("empty runtime account", {}, None, False),
        ("invalid runtime account", {}, None, False),
    ])
    for technology in ("docker", "podman", "container", "lxc", "lxd",
                       "containerd", "systemd-nspawn", "openvz"):
        cases.append((technology, {"virtualization_type": technology}, None, False))
    # Model detector results; no container or unsupported OS workload is started.
    for status in (0, 2):
        cases.append((f"detector status {status}", {}, status, False))
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ROOT / "ansible.cfg")
    with tempfile.TemporaryDirectory(prefix="dcmcp-host-guard-") as temporary:
        for index, (label, updates, detector_status, succeeds) in enumerate(cases):
            task_list = copy.deepcopy(guard)
            settings = copy.deepcopy(variables)
            settings["ansible_facts"].update(updates)
            if label == "missing runtime account":
                settings.pop("dcmcp_user")
            elif label == "empty runtime account":
                settings["dcmcp_user"] = ""
            elif label == "invalid runtime account":
                settings["dcmcp_user"] = "ROOT!"
            if detector_status is not None:
                detector = next(task for task in task_list
                                if task.get("register") == "dcmcp_container_probe")
                detector["ansible.builtin.command"]["argv"] = [
                    "/usr/bin/python3", "-c", f"raise SystemExit({detector_status})"]
            play = [{"name": "Host guard regression", "hosts": "localhost",
                     "gather_facts": False, "vars": settings, "tasks": task_list}]
            path = Path(temporary) / f"case-{index}.yml"
            path.write_text(yaml.safe_dump(play, sort_keys=False))
            result = subprocess.run([tool_executable("ansible-playbook"), "-i", "localhost,", "-c", "local",
                                     str(path)], cwd=ROOT, env=env, capture_output=True,
                                    text=True, timeout=60, check=False)
            output = result.stdout + result.stderr
            if (result.returncode == 0) != succeeds or "changed=0" not in output:
                raise RuntimeError(f"Host guard regression failed: {label}\n{output}")
            if "runtime account" in label and "Set dcmcp_user" not in output:
                raise RuntimeError(f"Explicit user guard did not provide guidance: {label}\n{output}")
            print(f"PASS: {label}", flush=True)
    print(f"All {len(cases)} native host guard cases passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
