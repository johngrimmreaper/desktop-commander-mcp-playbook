# Desktop Commander MCP Ansible

A **vendor-neutral [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)**
installer for [Desktop Commander](https://github.com/wonderwhy-er/DesktopCommanderMCP).
It deploys a pinned MCP server under an explicitly chosen, existing non-root
account on supported native Linux systems. It does **not** create accounts,
change sudoers, use a container or grant permissions beyond the account's
existing privileges.

**The default is standard MCP `stdio`.** Your compatible AI client launches
Desktop Commander locally or through SSH; **no OpenAI account, tunnel ID,
service, key or vendor-specific protocol is required**. For ChatGPT's cloud
connector, the optional `openai_tunnel` transport adds OpenAI's outbound
Secure MCP Tunnel. Other vendor-specific relays can be developed as separate
adapters, not dependencies of the MCP server.

This is a **breaking installer architecture**. Older managed installations and
release manifests are **not migrated or supported**. Existing operators must
plan a manual deactivation, removal and fresh installation; never run the new
role over an active old tunnel expecting an in-place upgrade. The playbook
rejects incompatible transport layouts instead of trying to convert them.

## Support and limitations

| Item | Current support |
| --- | --- |
| Server protocol | Standard MCP over `stdio` (default) |
| Optional remote access | Existing authenticated SSH, or explicitly configured OpenAI Secure MCP Tunnel |
| AI clients | Any client that can launch a standards-compliant stdio MCP subprocess; examples for Gemini CLI, Claude Code and Codex |
| Platforms | Native Ubuntu 26.04, RHEL 10, Fedora 43/44 and Arch/Omarchy; x86_64 or aarch64, glibc and systemd |
| Solaris | Local development installer for Oracle Solaris 11.4 CBE x86-64. Source build and stdio tested on CBE .90. See [Solaris setup](docs/solaris-portability.md#run-ansible-locally-on-the-solaris-vm). |
| Components pinned | Desktop Commander 0.3.4, Node 24.21.0 on Linux and system Node on Solaris; optional OpenAI tunnel-client 0.0.16 |
| Ansible | Controller ansible-core 2.21.x, `community.general` 13.5.0 for pacman |

MCP has standard `stdio` and Streamable HTTP transport bindings. This role
implements **stdio only** for vendor-neutral use; it does not expose an HTTP
MCP endpoint. A remote, browser-only service cannot connect directly to a
private SSH-stdio host without an appropriate supported bridge. Do not mistake
model/vendor compatibility for network reachability or an automatic cloud
connector. See the [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports).

## 1. Configure Ansible

From the repository checkout on a supported Ansible controller, install the
pinned development tools and collections:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml
cp -n inventory/hosts.example.yml inventory/hosts.yml  # remote SSH deployment
# Or use inventory/local.example.yml for a native local deployment.
vi inventory/hosts.yml
.venv/bin/python scripts/validate-inventory.py
```

The ignored `inventory/hosts.yml` must identify the **existing non-root**
`dcmcp_user`. For a local host, use the local inventory example, with
`ansible_connection: local` and `/usr/bin/python3`.

```yaml
all:
  children:
    mcp_servers:
      hosts:
        my_server:
          ansible_host: server.example.net
          ansible_user: ssh_operator
          ansible_python_interpreter: /usr/bin/python3
          dcmcp_user: mcp_operator
          dcmcp_transport: stdio
```

The runtime user is not necessarily the SSH/Ansible operator. All playbooks
run serially and preserve that user's existing Linux permissions. For sudo
password prompting, supply `--ask-become-pass` on the controller. Never place
passwords or API keys in inventory.

`dcmcp_transport` defaults to `stdio`; the explicit setting above is for
readability. You may omit it. Choose `openai_tunnel` **only** when you
specifically need OpenAI's relay; see [OpenAI transport setup](docs/openai-tunnel.md).

## 2. Install, configure and activate standard MCP

Install the immutable, checksum-verified Desktop Commander and Node release:

```bash
.venv/bin/ansible-playbook playbooks/install.yml
```

**Install stages files; it does not start an MCP server.** The active
Desktop Commander settings are deliberately created manually. Log in as the
selected `dcmcp_user` on the target, then:

```bash
umask 077
cp -n "/usr/local/share/desktop-commander-mcp/$(id -un)/desktop-commander.json.example" \
  "$HOME/.claude-server-commander/config.json"
chmod 600 "$HOME/.claude-server-commander/config.json"
vi "$HOME/.claude-server-commander/config.json"
```

The directory `.claude-server-commander` is **Desktop Commander's upstream
settings directory**, not a Claude-specific transport or dependency. The
sample is deliberately permissive: `allowedDirectories: []` and
`blockedCommands: []` do **not** constrain the existing Linux identity.
Review [security boundaries](docs/security.md) before granting agent access.

Then, back on the controller:

```bash
.venv/bin/ansible-playbook playbooks/preflight.yml
.venv/bin/ansible-playbook playbooks/activate.yml
```

This verifies the installed release and private configuration and atomically
selects the release. It does **not** start a background daemon in `stdio` mode.

The selected account's stdio entrypoint is:

```text
/usr/local/libexec/desktop-commander-mcp/USER/mcp-child
```

The MCP client launches it under `USER` on demand. An authorized client on
another machine may use:

```bash
ssh -T -o BatchMode=yes USER@YOUR_HOST \
  /usr/local/libexec/desktop-commander-mcp/USER/mcp-child
```

The SSH key, target account and host-key policy must already be configured;
no password prompts or SSH banners may contaminate the MCP protocol stream.
The launcher verifies that it is running under the expected Unix UID.

## 3. Configure compatible AI agents

Configure a **stdio** MCP server with the command and arguments above. Here
are examples for existing SSH access (use a direct `mcp-child` command for
local clients).

**Gemini CLI** (`mcpServers` inside its `settings.json`):

```json
{
  "mcpServers": {
    "desktop-commander": {
      "command": "ssh",
      "args": ["-T", "-o", "BatchMode=yes", "USER@YOUR_HOST", "/usr/local/libexec/desktop-commander-mcp/USER/mcp-child"]
    }
  }
}
```

**Codex CLI** (`config.toml`):

```toml
[mcp_servers.desktop-commander]
command = "ssh"
args = ["-T", "-o", "BatchMode=yes", "USER@YOUR_HOST", "/usr/local/libexec/desktop-commander-mcp/USER/mcp-child"]
```

**Claude Code**: register a stdio MCP server using its MCP CLI/settings and
the same SSH command and arguments. Do not assume that every AI product
supports remote private SSH or the same client-side configuration format.

Official references: [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md),
[Claude Code](https://code.claude.com/docs/en/mcp),
[Codex CLI](https://developers.openai.com/codex/mcp).

## 4. Operations and adapters

- **Stdio upgrade**: update reviewed upstream pins and checksums, run
  `install.yml`, `preflight.yml`, and `activate.yml`. Existing MCP clients may
  finish or be restarted independently. Use an independent SSH/console shell
  for deployment.
- **OpenAI cloud transport**: choose `dcmcp_transport: openai_tunnel`, then
  follow [the separate OpenAI adapter guide](docs/openai-tunnel.md). Only that
  transport installs a persistent systemd service, runtime key and health
  monitor; `upgrade.yml` and `doctor.py` are for its lifecycle.
- **Uninstall**: `playbooks/uninstall.yml` removes managed per-user files and
  optional systemd units while preserving the account home, manually created
  configuration and keys, and shared versioned release caches.
- **Run checks**: `.venv/bin/python scripts/check.py` runs unit tests, Ruff,
  ansible-lint and the playbook syntax checks without deploying. Host-changing
  integration tests are separate and must be executed only on an authorized
  disposable test VM.

No automatic migration is implemented. To change an account from an existing
transport or an older installation, stop/deactivate that service from an
independent session, remove the managed installation deliberately, review the
preserved account files, and install the desired transport afresh. Back up
runtime credentials and configuration before making those manual changes.

## Future platforms and public-release readiness

The generic MCP protocol is not tied to one AI company. The present **Ansible
implementation is still Linux-specific**, and some native Node dependencies
are platform-specific. In particular, Solaris needs native package, Node,
`sharp`/`esbuild`, paths and service-lifecycle verification before support can
be claimed. See the [Solaris audit](docs/solaris-portability.md).

Additional distribution backends and optional provider-specific relays should
reuse the same MCP build, security, non-root execution and stdio contract,
without hard-coding a vendor into the installer. Do not add new integrations
without their own documented configuration and native tests.

- [Current and historical validation](docs/validation.md)
- [Upstream source and pins](docs/upstream.md)
- [Omarchy deployment notes](docs/omarchy.md)
- [Security](docs/security.md)
- [LICENSE](LICENSE)
