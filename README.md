# Desktop Commander MCP + OpenAI Secure MCP Tunnel

Ansible automation for installing the open-source
[Desktop Commander MCP](https://github.com/wonderwhy-er/DesktopCommanderMCP) on
native Ubuntu 26.04, RHEL 10 or Fedora 43/44 and running it as a stdio
child of the official OpenAI client.
A single systemd service keeps the server available to the OpenAI backend;
desktop and mobile devices use ChatGPT. The mobile device does not run or
connect directly to the MCP server.

This is a native host daemon. Installation, startup, restarts and tool execution
do not require Docker, Podman, a container runtime or a Docker socket mount.
The daemon uses the host's systemd, filesystem and permissions of the
**explicitly selected existing Linux account**.

Installation stages files and versions. **Only explicit activation starts the
daemon**, after the operator manually copies and edits the configuration files
and preflight succeeds. The account/workspace must provide Secure MCP Tunnel
access and allow connector registration; installing this project does not
grant that access.

## Supported baseline

| Component | Baseline |
| --- | --- |
| Host | Native Ubuntu 26.04 LTS, RHEL 10 or Fedora 43/44; systemd, VM or physical host |
| Architecture | x86_64/amd64 or aarch64/arm64, glibc |
| Runtime user | **Required manual `dcmcp_user` in untracked inventory; no default or automatic selection** |
| Controller | Validated locally on Ubuntu 26.04 (Python 3.14) and RHEL 10.2 (Python 3.12), ansible-core 2.21.5; SSH targeting is supported |
| Desktop Commander | 0.3.1 |
| Node.js | 24.21.0, installed privately in the versioned release bundle |
| tunnel-client | 0.0.16, official Linux bundle with a pinned checksum |
| Lint | ansible-lint 26.9.0; dependencies in requirements-dev.txt |

The role never creates users, groups or sudoers rules. The operator MUST
select `dcmcp_user` in an ignored local inventory before **any** playbook can
run. It never uses the Ansible login account, root or a hardcoded `mcp_operator` as a
fallback. It preserves the selected existing user's permissions. The
example JSON leaves blockedCommands and
allowedDirectories empty, following the decision to use existing Linux
permissions and sudo access. The MCP does not guarantee interactive sudo:
authentication requirements follow the host's sudo configuration.

This grants a remote ChatGPT plugin substantial authority under the selected
Linux identity, not a container sandbox. Review the
[security boundaries and operator responsibilities](docs/security.md) before
activating a tunnel with access to sensitive projects or sudo.

The host guard rejects unsupported distribution releases, container targets
and architectures before installing anything. Native Ubuntu 26.04 on x86_64
has been integration-tested on an Ubuntu test VM. **RHEL 10.2 x86_64 was installed,
preflighted, activated and verified end-to-end through ChatGPT on a native VM
with SELinux Enforcing (2026-10-23).** Fedora 43/44 and arm64 have not had
native end-to-end validation. These results are host-specific, not blanket
production certification.
See [validation status](docs/validation.md).

## How it works

The desktop-commander-mcp.service unit runs a launcher that holds a local lock,
performs offline preflight and then executes tunnel-client run --config.
The official client starts mcp-child, which uses exec to run dist/index.js with
--no-onboarding. The unit runs as the manually selected `dcmcp_user` with
process HOME set to /var/lib/desktop-commander-mcp/home and WorkingDirectory
set by default to that account's real home from `/etc/passwd`. Desktop
Commander stores its config under
that process HOME. This keeps the daemon's config/caches separate from the
Remote Desktop Commander application and interactive MCP clients. The user
retains access to its normal home, Docker and sudo according to Linux permissions.

Its stdin/stdout connect to the tunnel exclusively for MCP
frames; stderr and daemon logs go to the journal.

Upstream code forwards SIGTERM/SIGINT to the child and shuts down the daemon
when the child exits or its pipes close. Restart=always also covers a clean
child exit. KillMode=control-group and TimeoutStopSec=45 terminate the unit's
processes before replacement; REPLs and child commands are interrupted during
a restart.

**Stdio permits only one active instance per tunnel ID, including during
upgrades.** The lock prevents two instances of this launcher on the same host.
It does not coordinate other hosts or a manually started tunnel-client.
Do not reuse the same ID in another daemon, service, VM or Codex-managed runtime.
Run Ansible operations sequentially, with one controller per host.

The tunnel uses outbound HTTPS to api.openai.com:443 without exposing a public
MCP endpoint. Health/UI bind to 127.0.0.1:8787 in the example. Installation also
requires HTTPS access to GitHub, nodejs.org and registry.npmjs.org, plus the host distribution's enabled trusted package repositories. Optional Desktop Commander features may use other destinations;
the process's total network traffic is not limited to the OpenAI host.

## 1. Prepare the controller and inventory

For a local deployment on the **validated Ubuntu 26.04 controller**, run these
commands from the checkout as an operator permitted to use sudo:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp -n inventory/local.example.yml inventory/hosts.yml
vi inventory/hosts.yml    # REQUIRED: replace the dcmcp_user placeholder
.venv/bin/python scripts/validate-inventory.py  # Fail early on malformed YAML/zero hosts
.venv/bin/ansible-playbook playbooks/install.yml
```

**You must manually configure `dcmcp_user`** in `inventory/hosts.yml`.
The file is excluded from Git by `.gitignore`. For example, on a local host:

```yaml
all:
  children:
    mcp_servers:
      hosts:
        localhost:
          ansible_connection: local
          ansible_python_interpreter: /usr/bin/python3
          dcmcp_user: alice  # REPLACE with an existing non-root Linux user
```

The committed inventory templates contain an **already space-indented**
`dcmcp_user: REPLACE_WITH_EXISTING_LINUX_ACCOUNT` line immediately below the
connection settings. Replace the placeholder with your actual existing Linux
account, for example `mcp_operator`. Do not comment out the line or use tabs for
YAML indentation. In `vi`, `:set expandtab shiftwidth=2 tabstop=2` can help.
The placeholder is intentionally invalid as a runtime account: an unchanged,
missing, blank, root or nonexistent user stops execution before installation
changes anything. Neither the login account nor a built-in default is used as
a fallback. No users, groups or sudo rules are created.

`dcmcp_user` is the account that runs the MCP systemd service and owns its
private configuration. It is independent of `ansible_user`, the SSH login
for Ansible. The process HOME remains the private fixed location described
below, while the default working directory comes from the selected account's
passwd home directory.

The local inventory uses `ansible_connection: local` and `/usr/bin/python3`;
no SSH or Docker is required. Installation needs the controller's existing
sudo rights. If sudo requires a password, add `--ask-become-pass`; never
commit that password. For a remote Linux host, copy `inventory/hosts.example.yml` to
`inventory/hosts.yml`, then manually set `ansible_host`, `ansible_user` and
`dcmcp_user`.

Changing `dcmcp_user` on an **already running installation** is not a user
migration. Its existing configuration and private files belong to the prior
account; transferring ownership requires a separate, controlled procedure.
Do not expect a simple variable change to migrate secrets or restart the
running service as a different user. To change the working directory, set
`dcmcp_workdir` in the ignored inventory and create that directory manually.

This feature selects the Linux runtime user only. **The current tunnel backend
is still the OpenAI Secure MCP Tunnel**; support for other AI tunnel protocols
would be a separate feature.

### RHEL 10 / Fedora 43-44 setup (RHEL 10.2 x86_64 validated; Fedora provisional)

Use an existing Ansible controller (an Ubuntu test VM is suitable) with an
SSH connection to the target; a pre-existing tunnel on the destination is
**not** required. Do not boot or change other VMs merely to test the playbook.

1. Make sure the target uses native systemd, with an existing non-root runtime
   user, working directory and sudo-capable SSH operator account. RHEL must
   already be registered to its licensed BaseOS/AppStream repositories.
2. On **RHEL 10**, ensure `ripgrep` is installed or available from an enabled,
   trusted repository. It is generally distributed through **EPEL 10** or
   **RHEL Extensions** rather than the base repository set. Enable the
   appropriate source manually, following your organization's policies:

   ```bash
   sudo dnf repolist --enabled
   sudo dnf list --available ripgrep
   # After enabling a trusted source, install if needed:
   sudo dnf install ripgrep
   ```

   The playbook checks this requirement *before changing packages* and does
   **not** enroll the machine, install `epel-release`, enable CodeReady Builder
   or bypass repository signature verification. On Fedora 43/44, ripgrep is
   available in Fedora's normal repositories.
3. From your controller, configure an ignored `inventory/hosts.yml`:

   ```yaml
   all:
     children:
       mcp_servers:
         hosts:
           rhel10:
             ansible_host: REPLACE_WITH_RHEL_IP_OR_HOSTNAME
             ansible_user: REPLACE_WITH_SSH_ACCOUNT
             ansible_python_interpreter: /usr/bin/python3
             dcmcp_user: REPLACE_WITH_EXISTING_RUNTIME_ACCOUNT
   ```

   For Fedora, change the host alias and address. Ansible installs Ubuntu
   dependencies with APT, RHEL 10 packages with DNF4, and Fedora 43/44 packages
   with DNF5; it uses platform-specific RPM package names and does not install
   a second Node.js through the system package manager.
4. Run `./.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/install.yml`
   on the controller, optionally with `--ask-become-pass`. This **only stages**
   the release. Manually configure the destination's tunnel YAML, runtime key
   and JSON as in section 2. Run the `preflight.yml` and then `activate.yml`
   from an SSH session independent of the managed service.
5. If the target uses SELinux, leave it **Enforcing**. The role restores default
   SELinux contexts on its own managed files and uses the system-labeled Python
   binary to launch the supervisor. No custom SELinux policies are installed.
   Check `systemctl status desktop-commander-mcp.service`,
   `journalctl -u desktop-commander-mcp.service`, `ls -lZ` on installed paths,
   and AVC denials with `ausearch -m AVC -ts recent` if activation fails.
   Any site-specific denial must be diagnosed; **do not use `setenforce 0`**.

For remote targets, package installation still requires correctly configured
RPM repositories and network access to GitHub, nodejs.org, npm and OpenAI.
The host-specific daemon runtime, immutable release layout, user selection,
config ownership and rollback behavior are otherwise unchanged. Full RHEL/Fedora
native integration tests remain pending.

Installation adds distribution-specific dependencies and downloads Node
and tunnel-client with SHA-256 verification, retrieves Desktop Commander source at an immutable commit,
verifies the lockfile's Git blob and uses npm ci --ignore-scripts.
All remote packages in the reviewed lockfile carry integrity hashes and use
the official npm registry. The one allowlisted local telemetry contract is
verified against the pinned Git source and its local-link manifest. The
explicit build uses the architecture's esbuild binary, already verified by npm.
It does not use npx, @latest, npm install or setup/remote/telemetry scripts.

The role performs syntax, version, SDK, sharp, esbuild and ripgrep smoke checks
when the operator runs it. These checks do not start Desktop Commander.
The system ripgrep package provides the fallback documented by upstream.
OS packages are managed by each distribution and are not frozen by this project.

The complete bundle is published by renaming it into:

```text
/opt/desktop-commander-mcp/releases/RELEASE_ID/
  node/
  mcp/
  tunnel/
  release.json
```

The installation's final message shows RELEASE_ID. Running install again reuses
that bundle if its manifest has the same pins, without rebuilding or changing
the active version. Different pins under the same ID cause a failure instead
of overwriting code.

## 2. MANUALLY copy and edit the active files

On the host, use a session belonging to the selected `dcmcp_user` account.
The role creates private directories but **never copies examples into these active files**:

| Active file | Owner/mode |
| --- | --- |
| /var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml | selected `dcmcp_user`, 0600 |
| /var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/runtime.key | selected `dcmcp_user`, 0600 |
| /var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json | selected `dcmcp_user`, 0600 |
| Both configuration directories | selected `dcmcp_user`, 0700 |

The role creates /var/lib/desktop-commander-mcp/home owned by the
configured `dcmcp_user`, with mode 0700. This is the daemon's process HOME,
not the operator's login home.
WorkingDirectory does not change Desktop Commander's configuration path.

```bash
umask 077
cp -n /usr/local/share/desktop-commander-mcp/tunnel.yaml.example "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml"
cp -n /usr/local/share/desktop-commander-mcp/desktop-commander.json.example "/var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json"
chmod 600 "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml" "/var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json"
vi "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml"
```

cp -n preserves existing files; update them manually when configuration already
exists. Replace REPLACE_WITH_PROVISIONED_TUNNEL_ID with the provisioned ID:
tunnel_ followed by 32 lowercase hexadecimal characters. Do not use the sample
ID from upstream documentation.

The YAML is valid and extensively commented. The JSON is strict and has no
comments; documentation for each field is installed at
/usr/local/share/desktop-commander-mcp/configuration.md. There is no implicit
YAML-to-JSON conversion or automatically generated active configuration.

Create the **runtime key** file without placing the key on the command line,
in shell history or in MCP environment variables. The following example
prompts for hidden input and refuses to overwrite an existing file:

```bash
python3 - <<'PY'
from getpass import getpass
import os
from pathlib import Path
key = getpass("Paste only the OpenAI runtime key: ")
target = Path("/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/runtime.key")
descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
with os.fdopen(descriptor, "w") as secret:
    secret.write(key + "\n")
PY
```

Do not use OPENAI_ADMIN_KEY or an administrative key in the daemon. The YAML
references runtime.key through upstream's native file: mechanism. The launcher
removes environment overrides, and the tunnel does not place this key in argv
or the child's environment. Processes retain the configured Linux user's
filesystem
permissions, including access to files that user owns.

## 3. Validate and activate

On the controller:

```bash
.venv/bin/ansible-playbook playbooks/preflight.yml
.venv/bin/ansible-playbook playbooks/activate.yml
```

Preflight validates the candidate bundle without changing the current selector,
opening MCP pipes, sending a handshake or contacting OpenAI. It rejects missing
files, placeholders, YAML with multiple documents/aliases/duplicate keys,
invalid JSON, empty or malformed keys, known administrative key prefixes,
secrets with incorrect ownership/modes, links in private files, unsafe paths,
missing/incompatible dependencies and bindings other than the supervised stdio
binding. Parser errors and probe output are not printed.

Offline validation cannot prove the key's type/server-side permissions,
product availability or the tunnel ID's existence/authorization. Those require
a key created for runtime use and online validation by the daemon.

Activation compares the release, YAML, key, unit and helpers using a private
fingerprint without printing secret contents. If an input changed, it stops
the unit, waits for the cgroup to terminate, switches current atomically and
starts the new version. An unchanged run keeps the existing instance running.
The unit is enabled at boot only during this step.

After startup, activation requires the managed systemd unit to be active, its
main process to own the loopback health listener, and /readyz to return HTTP 200.
The PID, systemd invocation and process start time must remain stable across
the request. Only then is the private success fingerprint recorded. The same
check runs for unchanged activation; an unrelated HTTP server cannot satisfy it.
That response still does not prove tools/list or a successful tool call.
Stdio discovery may remain not_observed until the connector's first request.
Invalid launcher configuration returns 78, preventing a restart loop.
An activation failure restores the previous selection/enablement and leaves
the service stopped for diagnosis; it does not declare a healthy rollback.

## 4. Provision the tunnel and connect in ChatGPT/OpenAI

Check access and permissions before creating the active files:

1. Open [Tunnels](https://platform.openai.com/settings/organization/tunnels) to
   create or inspect the tunnel. Your user needs Read + Manage to administer it.
2. Create a key in [Runtime API keys](https://platform.openai.com/settings/organization/api-keys)
   for a principal with Tunnels Read + Use on the target tunnel.
3. The connector user also needs Tunnels Read + Use. Roles and groups are managed
   in [Roles](https://platform.openai.com/settings/organization/people/roles)
   and [Groups](https://platform.openai.com/settings/organization/people/groups).
4. Manually copy the provisioned ID and runtime key; validate and activate.
5. Once the daemon is ready, open [ChatGPT connectors](https://chatgpt.com/#settings/Connectors).
   When the option is available for the account/workspace, choose Connection:
   Tunnel and select the tunnel or enter its ID, according to the enabled UI.
6. Discover tools and make a simple call, such as get_config or list_directory
   for the home directory. This is the connector's functional test.

Connector registration is deliberately manual: this project's Ansible code does
not manage the OpenAI account. If the Tunnel option is unavailable, check feature
enablement/permissions with the workspace administrator; the open-source binary
does not unlock account features.

Use the same account/workspace and chat/project on desktop and mobile.
The daemon stays on Ubuntu, and the backend uses the registered connector.
The mobile device does not receive the runtime key or an MCP installation.
Tool use on that surface depends on ChatGPT's available capabilities and
permissions; this project does not promise unconditional mobile support.

## Troubleshooting

On the host, using the existing sudo permissions:

```bash
systemctl status desktop-commander-mcp.service --no-pager
sudo journalctl -u desktop-commander-mcp.service -n 100 --no-pager
curl -fsS http://127.0.0.1:8787/healthz
curl -fsS http://127.0.0.1:8787/readyz
curl -fsS http://127.0.0.1:8787/health/mcp
```

Use the port you configured. To check that readiness belongs to this managed
daemon, run the same helper used by activation with existing sudo rights:

```bash
sudo python3 /usr/local/libexec/desktop-commander-mcp/readiness.py --unit desktop-commander-mcp.service --listen-addr 127.0.0.1:8787
```

The helper inspects the daemon's Linux /proc descriptors, so run it with sudo.
The curl commands alone do not establish listener ownership. /health/mcp
reports observations from the same child; readiness and discovery provide
different evidence. Do not expose health/UI on the network.

To run preflight directly as the configured service account, pass the user
**explicitly**, plus the RELEASE_ID reported by installation;
the current selector does not exist before the first activation:

```bash
env HOME=/var/lib/desktop-commander-mcp/home python3 /usr/local/libexec/desktop-commander-mcp/preflight.py --user YOUR_RUNTIME_USER --release /opt/desktop-commander-mcp/releases/RELEASE_ID
```

To validate the installed artifacts before creating active configuration,
use release-only mode as the runtime user. It checks executable versions, the
built entry point and native dependencies without reading keys or starting
either daemon:

```bash
env HOME=/var/lib/desktop-commander-mcp/home python3 /usr/local/libexec/desktop-commander-mcp/preflight.py --user YOUR_RUNTIME_USER --release-only --release /opt/desktop-commander-mcp/releases/RELEASE_ID
```

The official client's doctor command is optional. With the daemon stopped,
it checks upstream parsing and prerequisites. It inspects the stdio executable
without starting another child. It does not prove runtime permissions in OpenAI.
Use a clean environment and the active YAML:

```bash
env -i HOME=/var/lib/desktop-commander-mcp/home USER=YOUR_RUNTIME_USER SHELL=/bin/bash PATH=/opt/desktop-commander-mcp/current/node/bin:/usr/bin:/bin /opt/desktop-commander-mcp/current/tunnel/tunnel-client doctor --config "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml" --explain
```

| Symptom | Check |
| --- | --- |
| Preflight failure/exit 78 | Manually created files, ownership/modes, placeholders, home and dependencies |
| /readyz does not respond or return 200 | Unit, available port, TLS/DNS/outbound HTTPS, key and tunnel permissions |
| Daemon ready, tools missing | Correct connector/ID/workspace and discovery through ChatGPT |
| mcp_initialization_required | Caller must send initialize and notifications/initialized after child replacement |
| Another managed tunnel instance | Another launcher holds the lock; stop the previous unit and do not duplicate the ID |
| Sudo requests a password | Existing sudo authentication requirements; this project does not add NOPASSWD |
| PDF/Chrome unavailable | Optional feature outside the versioned browser baseline described below |

Preflight accepts stdio_send_initialized_notification as a boolean in tunnel
YAML when the observed caller needs that shim. The default false preserves
upstream's flow; the tunnel does not invent initialize or resend it after
replacing the child.

Upstream Desktop Commander attempts to locate or download stable Chrome for
PDF after MCP initialization. Installation/preflight do not exercise that
additional behavior. **This project does not install or pin Chrome and does not
claim reproducible or validated PDF/browser support**, especially on arm64.
For that scope, qualify and maintain a compatible browser separately before
enabling it.

## Upgrades and rollback

The pinned baseline is Desktop Commander **v0.3.1**. Both first-time installs
and upgrades use the exact upstream Git commit and lockfile, never a floating
branch, `npx`, `@latest`, or the paid Remote Desktop Commander installer.
Node 24 and the official OpenAI tunnel-client are bundled in each immutable
release. Current releases do not require changes to the active tunnel YAML,
runtime key or Desktop Commander JSON.

### New installation

Run `playbooks/install.yml` as described in section 1. Install *only stages* the
new release. Create the active files manually (section 2), run
`playbooks/preflight.yml`, then explicitly run `playbooks/activate.yml`.
Nothing is auto-activated on a new host.

### Upgrade a running installation

1. Update only the reviewed version/commit/lockfile pins in
   `roles/dcmcp/defaults/main.yml` when a new upstream release is verified.
   Keep SHA-256 checks for any changed Node/tunnel binary. Review upstream
   compatibility changes and the local-dependency allowlist in `release.yml`.
2. From an **independent SSH/console session**, run:

   ```bash
   cd /path/to/desktop-commander-mcp-ansible
   .venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/upgrade.yml --ask-become-pass
   ```

3. This single command refuses inactive/disabled or unconfigured hosts,
   stages the immutable bundle while production continues running, validates
   the config/key and candidate, and uses the existing controlled activation
   to stop the old cgroup, atomically switch `current`, start and check readiness.
   A subsequent invocation is idempotent if nothing has changed. Omit
   `--ask-become-pass` only if your sudo policy is already noninteractive.
4. Verify `systemctl status desktop-commander-mcp.service`, `/readyz`, the
   journal, tool discovery and a real command from ChatGPT. The old release is
   retained for rollback.

**Do not run the upgrade interactively through the exact MCP tunnel being
restarted.** Service shutdown terminates that terminal session and any child
Ansible process. Instead use SSH/console or launch the controller in a separate
systemd transient unit before the restart. This is also true for manual
`activate.yml` when you are connected through the production tunnel.

To run the upgrade **from an existing Desktop Commander session** when no
independent SSH session is available, detach the controller from its service
cgroup by using `scripts/upgrade-detached.sh`. The launcher validates an
**explicit local-only inventory**, invokes `sudo -v` to authenticate in the
current terminal if necessary, then starts a **root-owned transient systemd
unit**. Because the detached controller is already privileged, it needs no
stored sudo password, inherited sudo timestamp or interactive TTY after launch.
Its transient unit and logs survive the MCP restart. The detached launcher
**does not support SSH/remote inventories**; use an independent controller
for those. If password-based sudo cannot prompt in your current MCP session,
authenticate and launch from an independent SSH/console session instead.
No NOPASSWD sudoers changes are made:

```bash
cd /path/to/desktop-commander-mcp-ansible
bash scripts/upgrade-detached.sh
# After reconnecting, see the unit name printed above:
sudo journalctl -u dcmcp-upgrade-YYYYMMDDTHHMMSS.service --no-pager -n 100
```

An activation failure restores the previous release *selector and enablement*
and stops the daemon to avoid falsely claiming a healthy rollback. Run a manual
recovery through SSH/console, or use the detached upgrader's automatic recovery
attempt. This revised password-sudo detached path has unit/static tests but
has **not yet undergone a live RHEL upgrade test**; first trial should use an
independent console with rollback access. Recovery retries `preflight.yml` and
`activate.yml` on the prior bundle
and confirms readiness; it cannot fix invalidated credentials or remote access.

To manually roll back to an installed bundle's ID (restore compatible config
first, if necessary):

```bash
.venv/bin/ansible-playbook playbooks/preflight.yml -e dcmcp_target_release=PREVIOUS_RELEASE_ID
.venv/bin/ansible-playbook playbooks/activate.yml -e dcmcp_target_release=PREVIOUS_RELEASE_ID
```

The fingerprint excludes mutable counters/metadata in Desktop Commander's
JSON. To force an explicit restart after changing only that JSON:

```bash
.venv/bin/ansible-playbook playbooks/activate.yml -e dcmcp_restart=true
```

To rotate the key, deactivate, edit runtime.key manually while retaining mode
0600, run preflight and reactivate. Never copy secrets into inventory or logs.

## Deactivation and uninstallation

```bash
.venv/bin/ansible-playbook playbooks/deactivate.yml
.venv/bin/ansible-playbook playbooks/uninstall.yml
```

deactivate stops the children and daemon and disables startup at boot.
uninstall removes only this project's managed bundle/releases, cached downloads,
helpers, examples, unit and fingerprint. It preserves the selected user, sudoers,
Ubuntu dependencies, the entire daemon process home (including the three active files and keys),
the account's home and working-directory data.

Revoke the key/tunnel and remove the OpenAI connector when you stop using it.
Disposal of preserved private files remains an operator's manual decision.

## Read-only diagnostics (any supported host)

Run as the configured runtime user, directly from the checkout:

```bash
.venv/bin/python scripts/doctor.py
.venv/bin/python scripts/doctor.py --json
```

The doctor checks systemd status, the selected immutable release, runtime
identity, configuration file ownership/modes, managed-process-owned loopback
readiness (using the installed root-owned readiness helper), the MCP
child process and SELinux status. It never starts, stops or changes anything,
never needs sudo, and never prints API keys, tunnel IDs or configuration
contents. HTTP checks are restricted to the configured `127.0.0.1` health
listener, without redirects or proxies. Its exit code is 0 when the runtime
checks pass and 1 if unhealthy. This is a local health check, not proof that
ChatGPT is able to invoke every tool through the OpenAI control plane.

## Optional passive health monitoring

The production service is **not** restarted or changed to install monitoring.
Monitoring is disabled by default; the operator must explicitly opt in after
installation and activation:

```bash
.venv/bin/ansible-playbook playbooks/monitor-enable.yml --ask-become-pass
systemctl list-timers desktop-commander-mcp-health.timer
journalctl -u desktop-commander-mcp-health.service -n 30 --no-pager
```

A separate systemd timer checks the managed daemon about every five minutes
(after a short boot delay). It uses the **same existing Linux runtime user**,
reads the local private files, and calls the root-owned installed readiness
checker to confirm that `/readyz` actually belongs to the running managed
process. A failed check causes an unsuccessful **monitoring oneshot** and
appears in the journal, without leaking keys or config, and without restarting
the MCP service or interrupting active tools. The system journal's retention
policy still applies; this project provides no external alerts or email.

To disable **and remove** the optional timer, service and installed monitoring
helper without affecting the production daemon:

```bash
.venv/bin/ansible-playbook playbooks/monitor-disable.yml --ask-become-pass
```

The normal uninstall playbook removes optional monitoring before removing the
MCP files. Monitoring is deliberately not installed or enabled automatically
by `install.yml`, `activate.yml` or `upgrade.yml`. On host types without SELinux,
no SELinux setting is changed. On RHEL/Fedora, normal labels are restored only
to the new managed files. Verify the first timer results before relying on its
journald statuses; no automatic recovery action is attached to this timer.



## Native validation on Ubuntu 26.04

The offline check runner uses the tools installed alongside its Python interpreter,
so shell activation is **not** required. Run it directly in the repository:

```bash
.venv/bin/python scripts/check.py
```

If a required tool is absent from that virtual environment, the runner fails
with an actionable error rather than accidentally using a system-wide tool.
For the additional native Ubuntu 26.04 checks (some modify the host), activate
the virtual environment first:

```bash
source .venv/bin/activate
python scripts/test-ansible-guards.py
python scripts/test-idempotence.py --local
python scripts/test-release.py
python scripts/test-activation.py
python scripts/test-installed.py --local
```

check.py runs positive/negative preflight and readiness tests, ruff, ansible-lint
and syntax checks for all six playbooks. Unit tests use fixtures and simulated
dependency/process probes. They do not deploy or contact OpenAI.

test-ansible-guards.py executes the real early role guard with positive native
facts and negative container/unsupported-release/detector results. It may run
on native Ubuntu 26.04, RHEL 10 and Fedora 43/44 (synthetic facts only, no
installation); the destructive integration scripts remain Ubuntu-only until
ported and verified separately.

**test-idempotence.py performs a real installation on this host.** Run it only
on the development/server host you intend to modify, as an existing user with
sudo. It runs install twice, requires changed=0 on the second run and verifies
that active files, current, service state and enablement are preserved.

test-release.py exercises the real release role against the complete installed
bundle and a temporary root-owned manifest-only bundle. It requires changed=0
for complete reuse, rejection without modification for damaged reuse, and
success without any active configuration files.

test-activation.py validates a private offline candidate, then runs the real
post-preflight activation tasks with isolated selectors, stamps and systemd
units. It covers fresh and unchanged activation, failed-unit reset, unrelated
HTTP 200 listeners, failure restoration and failed-but-enabled rollback.
Only fixture paths/unit names and readiness retry duration are adapted.
Its local HTTP fixture is a daemon managed by systemd; it does not start the
OpenAI tunnel or transmit a synthetic key. It preserves production state and
removes its temporary units and files.

test-installed.py requires native Ubuntu 26.04, the installed bundle and the
existing runtime account's noninteractive sudo. It creates private temporary
fixtures rather than copying examples to production paths. It runs the actual
installed preflight and dependency probes, rejects malformed/placeholder/admin
keys and unsafe permissions, and tests real MCP initialization, tools/list,
get_config, list_directory and start_process through the pinned SDK.

A temporary systemd unit connects the SDK supervisor to the native stdio child,
then exercises restart and cgroup shutdown with a long-lived tool process.
Only that test unit uses PrivateNetwork=yes to prevent optional browser/feature
downloads. The production unit uses the host network and retains the account's
existing capabilities. No Docker is involved. The temporary unit and fixtures
are removed afterward.

On an unconfigured, inactive installation, it also verifies that the real CLI,
preflight/activate playbooks and installed service reject missing configuration,
return exit 78 without a restart loop, and remain disabled without a current
selector. It tests the Ansible Ubuntu 24.04 rejection with synthetic facts on
Ubuntu 26.04; it does not execute a test on Ubuntu 24.04.

These checks use a synthetic key only for offline parsing. They do not run an
authenticated tunnel or register a ChatGPT connector. Provision the real ID/key
manually and complete the connector test from section 4 for that evidence.



The old container recipe is retained only as [historical Docker reference](examples/docker/README.md).
It is not a supported deployment or validation target. The maintained test
path is the native Ubuntu 26.04 host.

--check does not model building a new release and is explicitly rejected.
Use syntax checks, actual installation and the idempotence test.

## Sources and validation status

See the [upstream inspection and pins](docs/upstream.md) and
[actual validation status](docs/validation.md). That record distinguishes native
host results, local MCP calls and authenticated OpenAI/ChatGPT tests.

## License

This repository's Ansible automation, helpers, tests and documentation are
licensed under the [MIT License](LICENSE). Installed upstream components and
their dependencies retain their own licenses and copyright notices.
