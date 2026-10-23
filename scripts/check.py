#!/usr/bin/env python3
"""Run the meaningful offline checks; no deployment and no persistent check artifacts."""
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def tool_executable(name: str) -> str:
    """Use tools installed for this interpreter, not unrelated commands on PATH."""
    if sys.prefix != sys.base_prefix:
        # Do not resolve sys.executable: the venv's python is often a symlink
        # into /usr/bin, and resolve() would lose the venv's bin directory.
        executable = Path(sys.executable).parent / name
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise FileNotFoundError(
                f"Required tool {name!r} not found or executable at {executable}. "
                "Install development requirements into the active Python environment."
            )
        return str(executable)
    executable = shutil.which(name)
    if executable is None:
        raise FileNotFoundError(f"Required tool {name!r} not found on PATH.")
    return executable


def main():
    try:
        ruff = tool_executable("ruff")
        ansible_lint = tool_executable("ansible-lint")
        ansible_playbook = tool_executable("ansible-playbook")
    except FileNotFoundError as exc:
        print(f"Offline checks cannot start: {exc}", file=sys.stderr)
        return 127

    env = os.environ.copy()
    env["ANSIBLE_CONFIG"] = str(ROOT / "ansible.cfg")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    if sys.prefix != sys.base_prefix:
        # Subprocesses (including ansible-lint) may invoke tools by name.
        env["PATH"] = os.pathsep.join((str(Path(sys.executable).parent), env.get("PATH", "")))
    checks = [
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        [ruff, "check", "roles/dcmcp/files", "scripts", "tests"],
        [ansible_lint],
    ]
    for playbook in sorted((ROOT / "playbooks").glob("*.yml")):
        checks.append([ansible_playbook, "-i", "inventory/hosts.example.yml",
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
