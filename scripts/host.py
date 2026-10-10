"""Guard deployment checks: Ubuntu 26.04 on a native systemd host only."""
from pathlib import Path
import subprocess


def require_native_host():
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            release[key] = value.strip('"')
    if release.get("ID") != "ubuntu" or release.get("VERSION_ID") != "26.04":
        raise SystemExit("This check requires Ubuntu 26.04; other releases are unsupported.")
    container = subprocess.run(["systemd-detect-virt", "--container"], capture_output=True,
                               text=True, check=False)
    if container.returncode != 1 or Path("/proc/1/comm").read_text().strip() != "systemd":
        raise SystemExit("This check requires a native systemd host, outside a container.")
