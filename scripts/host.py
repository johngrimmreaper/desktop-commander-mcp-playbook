"""Guard native test runners before they touch a real host."""
from pathlib import Path
import subprocess


def require_native_host(*, allow_rpm=False, allow_arch=False):
    """Keep destructive suites Ubuntu-only until explicitly ported and audited.

    Safe synthetic-facts tests may opt into the role's current RPM baselines.
    All suites still require systemd as PID 1 outside containers.
    """
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    host = (release.get("ID"), release.get("VERSION_ID"))
    ubuntu = host == ("ubuntu", "26.04")
    rpm = ((host[0] == "rhel" and host[1] is not None
            and host[1].split(".")[0] == "10")
           or host in (("fedora", "43"), ("fedora", "44")))
    arch = host[0] == "arch"  # Omarchy retains Arch Linux's ID in os-release.
    if not ubuntu and not (allow_rpm and rpm) and not (allow_arch and arch):
        supported = "Ubuntu 26.04"
        if allow_rpm:
            supported += ", RHEL 10, Fedora 43/44"
        if allow_arch:
            supported += ", Arch Linux/Omarchy"
        raise SystemExit(f"This native test requires {supported}; this host is unsupported.")
    container = subprocess.run(["systemd-detect-virt", "--container"], capture_output=True,
                               text=True, check=False)
    if container.returncode != 1 or Path("/proc/1/comm").read_text().strip() != "systemd":
        raise SystemExit("This check requires a native systemd host, outside a container.")
