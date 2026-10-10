# Native Ubuntu 26.04 validation

Updated on 2026-10-10. Checks ran directly on ubuntu-test-vm through Remote Desktop
Commander, using its existing mcp_operator account and sudo. No Docker/container
executor was used for these results.

The results below describe the implementation tested on that date.
Subsequent documentation-only changes did not alter the tested code.

## Environment

| Item | Observed value |
| --- | --- |
| Host | ubuntu-test-vm, native KVM VM; systemd PID 1 |
| OS | Ubuntu 26.04.1 LTS, VERSION_ID=26.04 |
| Architecture | x86_64 |
| Account | Existing non-root account; existing noninteractive sudo |
| Python | 3.14.4 |
| Controller/check tools | ansible-core 2.21.5, ansible-lint 26.9.0, Ruff 0.17.0, PyYAML 6.0.3 |
| Native bundle | Desktop Commander 0.2.52, Node 24.21.0, tunnel-client 0.0.16 |
| Production process HOME | /var/lib/desktop-commander-mcp/home, mcp_operator-owned, mode 0700 |
| Production working directory | /home/mcp_operator |

Ubuntu 26.04 is the only maintained deployment/validation target.
The Ubuntu 24.04 rejection test used synthetic Ansible facts on ubuntu-test-vm;
it did not run a workload on Ubuntu 24.04.

## Executed results

| Check | Result |
| --- | --- |
| scripts/check.py | PASS, exit 0 |
| Positive/negative offline preflight unit tests | PASS: 26 methods plus negative subcases; each starts from a valid fixture |
| Ruff | PASS, no errors |
| ansible-lint | PASS, zero failures/warnings; production profile satisfied |
| Ansible syntax | PASS, all five playbooks |
| Native host guard | PASS: Ubuntu 26.04, systemd, outside a container |
| First native Ansible install | PASS: ok=52 changed=23 unreachable=0 failed=0 |
| Second native Ansible install | PASS: ok=33 changed=0 unreachable=0 failed=0 |
| Node and tunnel archive integrity | PASS: cached downloads' SHA-256 values match the pinned manifest |
| Desktop Commander source | PASS: installed Git HEAD matches the pinned Desktop Commander source |
| Node, npm, sharp, esbuild, SDK, ripgrep and tunnel probes | PASS against the installed native bundle |
| Installed preflight with private synthetic fixtures | PASS; repeated fingerprint stable |
| Malformed YAML, placeholder/admin keys, public key mode and invalid JSON | PASS: installed CLI returns 78 without synthetic secret disclosure |
| Ansible Ubuntu 24.04 guard | PASS: rejects synthetic unsupported facts before any change |
| Real preflight.yml and activate.yml with missing files | PASS: both fail; production selector stays absent and service stays disabled |
| Real installed systemd launcher with missing files | PASS: exit 78, NRestarts=0; no tunnel/MCP child starts |
| Native MCP handshake and tools/list | PASS: SDK initializes the real Desktop Commander child and discovers 26 tools |
| Native get_config and list_directory calls | PASS using the isolated test HOME and directory marker |
| Native start_process call | PASS: UID 1000 and existing sudo work without new sudoers/user rules |
| Native systemd restart | PASS: old supervisor/MCP/tool processes exit before their replacements are observed |
| Native systemd stop | PASS: MCP and long-lived tool children are terminated |
| Container independence | PASS: installed unit has no Docker/Podman Requires/Wants/After/PartOf dependency |
| Uninstall preservation | PASS: managed code/unit removed; private HOME, mode-0600 fixture and OS dependencies retained |
| Reinstall after uninstall | PASS: ok=51 changed=20 unreachable=0 failed=0 |
| Second reinstall | PASS: ok=33 changed=0 unreachable=0 failed=0 |
| systemd-analyze verify | PASS during install and final host inspection |
| Existing Remote Desktop Commander configuration | PASS: stable settings hash and file owner/mode unchanged; shared directory mode remains 0775 |
| Cleanup | PASS: temporary systemd unit gone; native fixtures removed; no active config files or current selector created |
| Final production state | Unit installed, inactive and disabled; dedicated private directories remain |

The install/reinstall harness checks active files, current, enablement and runtime
state before/after. On ubuntu-test-vm the production files/selector were absent and
remained absent. It never copied the examples to active paths.

The maintenance check placed a private non-credential marker in the daemon's
HOME, ran uninstall, verified that marker/permissions survived, then reinstalled
twice and removed only the marker. No real active key/configuration was used.

## Reproduction

From the checkout on an authorized native Ubuntu 26.04 development/server host,
as the existing runtime user with its existing sudo rights:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/check.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-idempotence.py --local
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-installed.py --local
```

The idempotence command installs on that host. The installed-runtime command
uses temporary private configurations and a temporary systemd unit; it does
not overwrite production active files.

Its SDK supervisor owns a real stdio Desktop Commander child. It uses the
installed unit's KillMode=control-group and Restart=always settings, checks
that the supervisor/MCP/tool child belong to the same service cgroup, then
restarts and stops that unit. Only this test unit uses PrivateNetwork=yes
to prevent optional browser/feature downloads. Production uses the host network.

The real production unit was briefly started with missing configuration to
verify refusal. It returned 78 without executing tunnel-client run, was
reset to inactive, and was never enabled or authenticated.

## Limits and historical reference

Not validated: native arm64, authenticated OpenAI tunnel operation/readiness,
active tunnel upgrade/rollback, ChatGPT/mobile registration or tool calls
through the OpenAI backend, and optional browser/PDF behavior. MCP tools were
tested through a local SDK stdio connection, not through an authenticated tunnel.

No real tunnel ID/key was provisioned, read or transmitted. Account/workspace
feature availability and Tunnels Read + Use permissions still require actual
provisioning and an online connector test.

The earlier container recipe is kept only under examples/docker.
It is not the maintained test/deployment path. See docs/upstream.md for sources,
pins and the original external-guide access limitation.
