#!/usr/bin/env python3
"""Run the meaningful offline checks; no deployment and no persistent check artifacts."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ROOT / "ansible.cfg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    checks = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ["ruff", "check", "roles/dcmcp/files", "scripts", "tests"],
        ["ansible-lint"],
    ]
    for playbook in sorted((ROOT / "playbooks").glob("*.yml")):
        checks.append(["ansible-playbook", "-i", "inventory/hosts.example.yml",
                       "--syntax-check", str(playbook)])
    for command in checks:
        print("Running: " + " ".join(command), flush=True)
        result = subprocess.run(command, cwd=ROOT, env=env, check=False)
        if result.returncode:
            return result.returncode
    print("Offline unit, lint and Ansible syntax checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
