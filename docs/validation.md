# Deployment validation

## Maintenance validation (2026-10-23)

On RHEL 10.2, the independent `.venv/bin/python scripts/check.py` runner
completed with no shell activation, and the synthetic host-facts integration
suite passed all **26** positive/negative cases on a native RHEL 10 host.
The non-destructive `scripts/doctor.py --json` returned `healthy: true` with
systemd, release, runtime user, private config, loopback health, readiness,
MCP child and SELinux Enforcing checks all positive. The detached upgrade
refactor is validated by static/unit tests only; no RHEL live upgrade was
attempted.
A separate harmless root-owned transient systemd test unit validated
`systemd-run --wait --pipe --collect` with `TRANSIENT_UID=0`, `HOME=/root`,
and the expected working directory; it exited successfully without calling
any Ansible upgrade playbook. The existing production systemd service was
not restarted or upgraded.

## Native RHEL 10.2 integration and live ChatGPT verification (2026-10-23)

**Validated on one native x86_64 RHEL 10.2 (Coughlan) KVM VM with
SELinux `Enforcing`.** A local Ansible 2.21.5 controller running under existing
non-root `mcp_operator` installed and activated the pinned release. The required
RPMs were resolved from pre-enabled repositories, including `ripgrep`.
The machine and repositories were provisioned separately; this test does not
show that fresh unregistered RHEL hosts have those dependencies available.

| Check | Observed result |
| --- | --- |
| Inventory/facts | `RedHat`, major 10, version 10.2; local inventory parsed correctly |
| Offline checks | 41 unit tests, Ruff, ansible-lint and six playbook syntax checks passed before installation |
| First install | `ok=63 changed=25 failed=0` |
| Second install | `ok=44 changed=0 failed=0`; release reused without rebuilding |
| Offline preflight | `ok=13 changed=0 failed=0` |
| Activation | `ok=29 changed=3 failed=0` and managed readiness succeeded |
| systemd/SELinux | Service active, enabled; `getenforce` returned `Enforcing` |
| HTTP health | `http://127.0.0.1:8787/readyz` returned `ready` |
| OpenAI control plane | Tunnel metadata fetched and tunnel-client started successfully |
| ChatGPT live MCP call | `get_config` and `start_process` succeeded via the configured MCP connector |
| Live command results | `/etc/redhat-release` reported RHEL 10.2; `getenforce` reported `Enforcing`; service `active`; readiness `ready` |

No active credentials were added to Git, and the live plugin verification was
read-only. Installation, activation, and actual ChatGPT MCP execution are now
proven for **this RHEL 10.2 host**. We have **not** run the complete Ubuntu-only
native destructive regression suite on RHEL, nor tested Fedora, arm64, RHEL
fresh-subscription setup, reboot persistence or a live RHEL upgrade/rollback.
Do not extrapolate this result to every RHEL configuration.

## Initial provisional RPM implementation (historical, before native verification)

The Ansible role now selects APT on Ubuntu 26.04, DNF4 on RHEL 10, and DNF5
on Fedora 43/44. RPM dependency names are explicitly listed rather than
translated through guessed package aliases. RHEL ripgrep must be installed or
available from previously enabled trusted repositories; no subscriptions,
EPEL configuration or SELinux policy are changed automatically. The role
uses the system Python as the systemd entrypoint for RPM systems and applies
standard SELinux file contexts to managed files when SELinux is enabled.

**At the time of this initial implementation, neither RPM target had been validated.**
No RHEL or Fedora VM was available during that earlier change. Successful synthetic fact, source, lint and
syntax checks **do not demonstrate that installation, DNF operations, native
Node dependencies, SELinux Enforcing activation or tunnel connectivity work
on real RHEL/Fedora machines**. Actual integration requires authorized VM
access; subsequent RHEL 10.2 native results are now recorded above. At the time,
Ubuntu 26.04 was the only system with end-to-end MCP/systemd tests.

On an Ubuntu test VM the synthetic Ansible guard accepted RHEL 10.0/10.1 and Fedora
43/44, and rejected RHEL 9, Debian 13, Fedora 45 beta, Ubuntu 24.04 and
container cases (24 total cases). The Ansible playbook syntax, Ruff,
ansible-lint and all 41 unit tests passed. Templates were rendered with
synthetic Ubuntu, RedHat and Fedora facts to confirm the expected systemd
ExecStart and configurable user. Two native Ubuntu install/idempotence runs
both had `changed=0`, with production configuration, release selector and
service state preserved.

Ubuntu's stable production service was not restarted while adding RPM support.

# Native Ubuntu 26.04 validation

## Explicit runtime-account selection validation (2026-10-22)

The installation no longer defaults to the `mcp_operator` account. Operators must
manually set `dcmcp_user` in the Git-ignored `inventory/hosts.yml`; distributed
examples originally contained commented placeholders (the current examples now
contain a space-indented placeholder value). The runtime-user guard is the
first task in the common `context.yml`, before user lookups or installation
mutations. The standalone Python preflight CLI also requires `--user`.

| Check | Result |
| --- | --- |
| No defaults/example inventory user | PASS at the time: templates then omitted the live key; current templates provide an explicit placeholder, never a usable runtime identity |
| Missing, empty, invalid runtime account | PASS: native Ansible guard refuses them with changed=0 and explicit instruction |
| Missing user in real install.yml execution | PASS: failed=1 changed=0, production MCP remains running |
| Missing user in real uninstall.yml execution | PASS: failed=1 changed=0, existing service and release selector untouched |
| Valid private inventory preflight | PASS: changed=0 with explicit runtime account, no service restart |
| Previously supported native/container guard cases | PASS: all 17 guard regressions |
| Local install with explicit user | PASS: first replay changed=2 for updated helper/unit, second replay changed=0, configuration/selector/activation preserved |
| Direct standalone preflight without `--user` | PASS: argparse rejects invocation with exit code 2 |

User selection is now explicit; it does not change the OpenAI-specific tunnel
backend nor implement migration between users on an already deployed host.


## Update validation on 2026-10-22

This update upgrades the pinned Desktop Commander source from 0.2.52
to **0.3.1**.
The Node.js 24.21.0 and OpenAI tunnel-client 0.0.16 pins were kept.

| Check | Result |
| --- | --- |
| Official v0.3.1 tag and lockfile Git blob | Verified against upstream (`b1c6da69633e597dab119e1173935523a4d4caa8`) |
| New vendored telemetry-contract allowlist | Matched versioned Git sources, local link and lock metadata; remote packages retain hash/registry verification |
| Native 0.3.1 install/build | PASS: ok=54 changed=11 failed=0; old 0.2.52 selected and running throughout staging |
| New candidate preflight | PASS, changed=0; no live service restart |
| Offline unit tests, Ruff, ansible-lint and playbook syntax | PASS, including new upgrade.yml |
| Release-only and damaged-bundle regression | PASS, complete pinned release reuse changed=0 |
| Install idempotence while running | PASS: two replays changed=0, production selector/state/operator config preserved |
| Upgrade guard with forced mismatched target | PASS: stopped before mutation with failed=1, changed=0, old daemon remains active |
| Detached production upgrade with systemd-run | PASS: 2026-10-22 22:59 UTC, ok=93 changed=4 failed=0 |
| Production daemon after upgrade | PASS: v0.3.1 selected, service active and enabled, /readyz=200, official tunnel-client 0.0.16 and Node 24.21.0 |
| Post-upgrade activation regression | PASS: all fixture activation, unchanged-PID, rollback selection and readiness ownership cases, including fixture cleanup |
| Post-upgrade native SDK/systemd test | PASS: 25 MCP tools; get_config/list_directory/start_process; cgroup restart and stop; production untouched |
| Native tool comparison | v0.2.52 exposed 26; v0.3.1 exposes 25. `get_prompts` was removed upstream; the other 25 names are unchanged |

The running upstream MCP changes its own usage statistics in `config.json`.
The idempotence and activation tests now exclude only these mutable counters
while still comparing operator settings and permissions, avoiding false positives.

The upgraded daemon reconnected through the production ChatGPT tunnel, and a
live MCP tool call reached ubuntu-test-vm after the restart. This verifies the channel
for the present session, not every future authentication/network condition.
The old v0.2.52 bundle was retained for rollback. An incomplete, unselected
v0.3.0 staging directory from the interrupted version investigation was removed.


Updated on 2026-10-10. Checks ran directly on ubuntu-test-vm through Remote Desktop
Commander, using its existing mcp_operator account and sudo. No Docker/container
executor was used for these results.

The results below describe the functional implementation tested on that date.
Subsequent license and documentation changes did not alter the tested code.

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

At the time of this historical validation, Ubuntu 26.04 was the only
deployment target. New RPM targets are provisional as documented above.
The Ubuntu 24.04 rejection test used synthetic Ansible facts on ubuntu-test-vm;
it did not run a workload on Ubuntu 24.04.

## Executed checks

The following results were executed directly on ubuntu-test-vm after the relevant
fixes. The final activation suite was repeated against the updated installed
preflight helper. No container executor, real tunnel ID or runtime key was used.

| Check | Result |
| --- | --- |
| scripts/check.py | PASS, exit 0; 34 unit tests, Ruff, ansible-lint and all five playbook syntax checks |
| Native Ansible host guard | PASS, 14 cases: VM/physical facts accepted; Ubuntu 24.04, eight container types, unknown container guest technology and detector status 0/2 rejected with changed=0 |
| Fresh disabled-unit activation | PASS after daemon-reload; starts the private systemd HTTP fixture and records success |
| Unchanged activation | PASS, changed=0; same main PID and systemd invocation |
| Retained failed-unit reset and recovery | PASS; reset-failed errors are not broadly ignored |
| Unrelated HTTP 200 with a failed unit | PASS: activation fails, no success stamp, first selector removed, prior disabled state restored |
| Unrelated HTTP 200 with a running non-listening unit | PASS: activation fails because the main process does not own the listener |
| Unchanged-input readiness with an unrelated listener | PASS: fails without claiming health or restarting the unchanged fixture |
| Failed-but-enabled replacement rollback | PASS: previous selector and enablement restored, no live service process; no healthy rollback claim |
| Recovery after failed readiness | PASS with the valid local fixture |
| Release-only installed artifact validation | PASS without active configuration/key files or MCP/tunnel startup |
| Manifest-only damaged bundle | PASS: actual release role rejects missing executables; bundle remains unchanged |
| Complete bundle reuse | PASS, changed=0; no active configuration files created |
| First install after release-validator update | PASS: ok=38 changed=1 unreachable=0 failed=0 |
| Second install after update | PASS: ok=38 changed=0 unreachable=0 failed=0; active files, selector and service state preserved |
| Installed preflight and real dependency probes | PASS; positive/negative fixtures, stable fingerprint and redacted errors |
| Real missing-configuration refusal | PASS: CLI/launcher exit 78, preflight/activate playbooks fail offline; no selector, enablement or restart loop |
| Native MCP initialization and calls | PASS: 26 tools; get_config, list_directory, start_process, existing UID/sudo |
| Native stdio systemd restart and stop | PASS: old supervisor, MCP and tool children exit; stop terminates all fixture children |
| Final cleanup/state | PASS: temporary units and damaged release removed; production inactive/disabled, current selector and three active files absent |

The activation regression validates a real installed bundle using private
synthetic configuration, then loads the real post-preflight activation tasks.
It redirects only fixture paths, the unit name and retry duration. The local
HTTP fixture runs as the existing user under systemd, allowing real checks of
PID ownership, listener ownership, first activation, idempotence and rescue.
It does not start tunnel-client run or authenticate to OpenAI. The full
production preflight/activate playbooks are separately exercised for missing
configuration refusal.

The native release test runs the actual release role against both the installed
bundle and a root-owned manifest-only fixture under the managed releases
directory. It uses an empty private process HOME to prove that installing or
reusing a release does not require or create active configuration.

## Reproduction

From the checkout on an authorized native Ubuntu 26.04 development/server host,
as the existing runtime user with its existing sudo rights:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python scripts/check.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-ansible-guards.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-idempotence.py --local
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-release.py
PATH="$PWD/.venv/bin:$PATH" .venv/bin/python scripts/test-activation.py
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

## Limits

Not validated: native arm64, authenticated OpenAI tunnel activation or
upgrade/rollback, ChatGPT/mobile registration or backend tool calls, and
optional browser/PDF behavior. The MCP tool checks use a local SDK stdio
connection; activation state/rollback checks use private systemd HTTP fixtures.

No real tunnel ID/key was provisioned, read or transmitted. Account/workspace
feature availability and Tunnels Read + Use permissions still require actual
provisioning and an online connector test.

The earlier container recipe remains only under examples/docker. It is not a
maintained deployment or validation path. See docs/upstream.md for sources,
pins and the original external-guide access limitation.
