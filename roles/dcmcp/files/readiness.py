#!/usr/bin/python3
"""Require readiness from the listener owned by this systemd service's main process."""
import argparse
import http.client
from pathlib import Path
import re
import subprocess
import sys


class NotReady(Exception):
    """Only fixed diagnostics are exposed; never echo HTTP bodies or subprocess output."""


def require(condition, message):
    if not condition:
        raise NotReady(message)


def service_identity(unit):
    result = subprocess.run(
        ["/usr/bin/systemctl", "show", unit, "--property=LoadState", "--property=ActiveState",
         "--property=SubState", "--property=MainPID", "--property=InvocationID"],
        capture_output=True, text=True, timeout=5, check=False)
    require(result.returncode == 0, "The managed service state is unavailable.")
    state = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    require(state.get("LoadState") == "loaded" and state.get("ActiveState") == "active"
            and state.get("SubState") == "running", "The managed service is not running.")
    pid = int(state.get("MainPID", "0"))
    invocation = state.get("InvocationID", "")
    require(pid > 0 and re.fullmatch(r"[0-9a-f]{32}", invocation),
            "The managed service has no live main process.")
    # PID plus start time distinguishes a process even if Linux recycles its PID.
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
    return pid, invocation, int(fields[19])


def require_owned_listener(pid, port):
    inodes = set()
    exact_loopback = False
    # Linux exposes all listeners in the process network namespace here. Reject
    # an ambiguous/wildcard listener and require ownership by the daemon itself.
    for line in Path(f"/proc/{pid}/net/tcp").read_text().splitlines()[1:]:
        fields = line.split()
        address, raw_port = fields[1].split(":")
        if fields[3] == "0A" and int(raw_port, 16) == port:
            if address not in ("0100007F", "00000000"):
                continue
            inodes.add(int(fields[9]))
            exact_loopback |= address == "0100007F"
            require(address != "00000000", "Health must bind only to IPv4 loopback.")
    owned = set()
    for descriptor in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = descriptor.readlink()
        except FileNotFoundError:
            continue  # An unrelated descriptor can close while it is inspected.
        match = re.fullmatch(r"socket:\[([0-9]+)\]", str(target))
        if match:
            owned.add(int(match[1]))
    require(exact_loopback and inodes and inodes <= owned,
            "The managed main process does not exclusively own the health listener.")


def check(unit, address):
    require(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.@-]{0,200}\.service", unit),
            "The service name is invalid.")
    require(re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", address),
            "The health address must be explicit IPv4 loopback.")
    port = int(address.split(":")[1])
    require(1024 <= port <= 65535, "The health port is invalid.")
    before = service_identity(unit)
    require_owned_listener(before[0], port)
    # A direct connection avoids proxy, redirect and credential inheritance.
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
    try:
        connection.request("GET", "/readyz")
        response = connection.getresponse()
        require(response.status == 200, "The managed tunnel has not reported local readiness.")
    finally:
        connection.close()
    after = service_identity(unit)
    require(after == before, "The managed process changed during the readiness check.")
    require_owned_listener(after[0], port)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--unit", required=True)
    parser.add_argument("--listen-addr", required=True)
    args = parser.parse_args()
    try:
        check(args.unit, args.listen_addr)
    except NotReady as error:
        print("Readiness failed: " + str(error), file=sys.stderr)
        return 1
    except (OSError, ValueError, IndexError, subprocess.SubprocessError, http.client.HTTPException):
        print("Readiness failed: managed process, listener or HTTP endpoint is unavailable.",
              file=sys.stderr)
        return 1
    print("Managed daemon readiness passed (local; OpenAI authentication is not verified).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
