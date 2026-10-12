# Desktop Commander MCP + OpenAI Secure MCP Tunnel

Ansible automation for installing the open-source
[Desktop Commander MCP](https://github.com/wonderwhy-er/DesktopCommanderMCP) on
headless Ubuntu 26.04 and running it as a stdio child of the official OpenAI client.
A single systemd service keeps the server available to the OpenAI backend;
desktop and mobile devices use ChatGPT. The mobile device does not run or
connect directly to the MCP server.

This is a native host daemon. Installation, startup, restarts and tool execution
do not require Docker, Podman, a container runtime or a Docker socket mount.
The daemon uses the host's systemd, filesystem and existing mcp_operator permissions.

Installation stages files and versions. **Only explicit activation starts the
daemon**, after the operator manually copies and edits the configuration files
and preflight succeeds. The account/workspace must provide Secure MCP Tunnel
access and allow connector registration; installing this project does not
grant that access.

## Supported baseline

| Component | Baseline |
| --- | --- |
| Host | Ubuntu 26.04 LTS only, headless, native systemd (VM or physical host) |
| Architecture | x86_64/amd64 or aarch64/arm64, glibc |
| Runtime user | Existing mcp_operator account and existing sudo; dedicated process HOME |
| Controller | Ubuntu 26.04, Python 3.14 and ansible-core 2.21.5 |
| Desktop Commander | 0.2.52 |
| Node.js | 24.21.0, installed privately in the versioned release bundle |
| tunnel-client | 0.0.16, official Linux bundle with a pinned checksum |
| Lint | ansible-lint 26.9.0; dependencies in requirements-dev.txt |

The role does not create users, groups or sudoers rules. It preserves the
existing user's permissions. The example JSON leaves blockedCommands and
allowedDirectories empty, following the decision to use existing Linux
permissions and sudo access. The MCP does not guarantee interactive sudo:
authentication requirements follow the host's sudo configuration.

Ansible rejects Ubuntu 24.04, other distributions and container targets before
installation. The supported deployment and validation environment is a native
Ubuntu 26.04 systemd host. Native x86_64 installation and MCP/systemd tests
passed on ubuntu-test-vm; arm64 download pins are provided, but native arm64 remains
untested. See the
[validation status](docs/validation.md).

## How it works

The desktop-commander-mcp.service unit runs a launcher that holds a local lock,
performs offline preflight and then executes tunnel-client run --config.
The official client starts mcp-child, which uses exec to run dist/index.js with
--no-onboarding. The unit runs as the existing mcp_operator user with process HOME set to
/var/lib/desktop-commander-mcp/home and WorkingDirectory set to the account's
passwd home (normally /home/mcp_operator). Desktop Commander stores its config under
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
requires HTTPS access to GitHub, nodejs.org and registry.npmjs.org, plus Ubuntu
mirrors. Optional Desktop Commander features may use other destinations;
the process's total network traffic is not limited to the OpenAI host.

## 1. Prepare the controller and inventory

For a local deployment on ubuntu-test-vm or another native Ubuntu 26.04 host, run
these commands from the checkout as the existing mcp_operator user:

```bash
sudo apt-get update
sudo apt-get install -y python3-venv
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
cp -n inventory/local.example.yml inventory/hosts.yml
nano inventory/hosts.yml
.venv/bin/ansible-playbook playbooks/install.yml
```

The local inventory uses ansible_connection: local and /usr/bin/python3.
It uses neither SSH nor Docker. Install needs the existing account's sudo rights.
If sudo requires a password, add --ask-become-pass; do not commit the password.

For a separate Ubuntu 26.04 server, use inventory/hosts.example.yml instead;
that inventory uses ansible_user: mcp_operator. Local inventories, configuration and
secrets are covered by .gitignore. To change the working directory, set
dcmcp_workdir in inventory and create the directory manually.

Installation adds Ubuntu dependencies, downloads Node and tunnel-client with
SHA-256 verification, retrieves Desktop Commander source at an immutable commit,
verifies the lockfile's Git blob and uses npm ci --ignore-scripts. The inspected
lockfile's 1,142 dependency entries have integrity hashes and official registry
URLs. The explicit build uses the architecture's esbuild binary, already
verified by npm; it does not use npx, @latest, npm install or setup/remote/
telemetry scripts.

The role performs syntax, version, SDK, sharp, esbuild and ripgrep smoke checks
when the operator runs it. These checks do not start Desktop Commander.
Ubuntu's ripgrep package provides the fallback documented by upstream.
OS dependencies are maintained by Ubuntu and are not frozen by this project.

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

On the host, use a session belonging to the existing mcp_operator account. The role
creates private directories but **never copies examples into these active files**:

| Active file | Owner/mode |
| --- | --- |
| /var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml | mcp_operator, 0600 |
| /var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/runtime.key | mcp_operator, 0600 |
| /var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json | mcp_operator, 0600 |
| Both configuration directories | mcp_operator, 0700 |

The role creates /var/lib/desktop-commander-mcp/home with owner mcp_operator and
mode 0700. This is the daemon's process HOME, not the operator's login home.
WorkingDirectory does not change Desktop Commander's configuration path.

```bash
umask 077
cp -n /usr/local/share/desktop-commander-mcp/tunnel.yaml.example "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml"
cp -n /usr/local/share/desktop-commander-mcp/desktop-commander.json.example "/var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json"
chmod 600 "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml" "/var/lib/desktop-commander-mcp/home/.claude-server-commander/config.json"
nano "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml"
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
or the child's environment. Processes retain the mcp_operator user's filesystem
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

To run preflight directly as mcp_operator, pass the RELEASE_ID reported by installation;
the current selector does not exist before the first activation:

```bash
env HOME=/var/lib/desktop-commander-mcp/home python3 /usr/local/libexec/desktop-commander-mcp/preflight.py --release /opt/desktop-commander-mcp/releases/RELEASE_ID
```

To validate the installed artifacts before creating active configuration,
use release-only mode as the runtime user. It checks executable versions, the
built entry point and native dependencies without reading keys or starting
either daemon:

```bash
env HOME=/var/lib/desktop-commander-mcp/home python3 /usr/local/libexec/desktop-commander-mcp/preflight.py --release-only --release /opt/desktop-commander-mcp/releases/RELEASE_ID
```

The official client's doctor command is optional. With the daemon stopped,
it checks upstream parsing and prerequisites. It inspects the stdio executable
without starting another child. It does not prove runtime permissions in OpenAI.
Use a clean environment and the active YAML:

```bash
env -i HOME=/var/lib/desktop-commander-mcp/home USER=mcp_operator SHELL=/bin/bash PATH=/opt/desktop-commander-mcp/current/node/bin:/usr/bin:/bin /opt/desktop-commander-mcp/current/tunnel/tunnel-client doctor --config "/var/lib/desktop-commander-mcp/home/.config/desktop-commander-mcp/tunnel.yaml" --explain
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

1. Update dcmcp_desktop_version/revision/lock_blob, dcmcp_node_version/checksums
   and dcmcp_tunnel_version/checksums using verified official sources. This
   implementation supports Node major version 24.
2. Run install: the active runtime and current selection stay as they were.
   Every reused bundle is revalidated; a matching release.json alone is not
   accepted as proof of a complete installation. A damaged bundle fails without
   being overwritten. Restore a verified bundle while stopped, or stage a new ID.
3. Read upstream compatibility notes and update the active files manually.
4. Run preflight and activate. Each complete bundle contains Node, MCP,
   dependencies and the tunnel, avoiding a mixed-version upgrade.
5. Check the journal, /readyz, discovery and a real call through the connector.

Previous releases are retained. To roll back, use an installed bundle's ID and,
when needed, manually restore compatible configuration:

```bash
.venv/bin/ansible-playbook playbooks/preflight.yml -e dcmcp_target_release=PREVIOUS_RELEASE_ID
.venv/bin/ansible-playbook playbooks/activate.yml -e dcmcp_target_release=PREVIOUS_RELEASE_ID
```

The same flow stops the old instance before starting the replacement. Do not
perform simultaneous rollouts for that ID. Reinstalling the baseline does not
undo a rollback: install does not switch current.

The fingerprint excludes mutable counters/metadata in Desktop Commander's
JSON. To apply changes only to that JSON with an explicit restart:

```bash
.venv/bin/ansible-playbook playbooks/activate.yml -e dcmcp_restart=true
```

To rotate the key, deactivate, edit runtime.key manually while retaining mode
0600, run preflight and reactivate. Do not copy secrets into inventory or logs.

## Deactivation and uninstallation

```bash
.venv/bin/ansible-playbook playbooks/deactivate.yml
.venv/bin/ansible-playbook playbooks/uninstall.yml
```

deactivate stops the children and daemon and disables startup at boot.
uninstall removes only this project's managed bundle/releases, cached downloads,
helpers, examples, unit and fingerprint. It preserves the mcp_operator user, sudoers,
Ubuntu dependencies, the entire daemon process home (including the three active files and keys),
the account's home and working-directory data.

Revoke the key/tunnel and remove the OpenAI connector when you stop using it.
Disposal of preserved private files remains an operator's manual decision.

## Native validation on Ubuntu 26.04

Run checks directly in the Ubuntu 26.04 VM or physical host:

```bash
source .venv/bin/activate
python scripts/check.py
python scripts/test-ansible-guards.py
python scripts/test-idempotence.py --local
python scripts/test-release.py
python scripts/test-activation.py
python scripts/test-installed.py --local
```

check.py runs positive/negative preflight and readiness tests, ruff, ansible-lint
and syntax checks for all five playbooks. Unit tests use fixtures and simulated
dependency/process probes. They do not deploy or contact OpenAI.

test-ansible-guards.py executes the real early role guard with positive native
facts and negative container/unsupported-release/detector results. Synthetic
facts model the rejected systems; all execution stays on Ubuntu 26.04.

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
