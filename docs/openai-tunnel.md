# Optional OpenAI Secure MCP Tunnel adapter

The core Ansible role defaults to vendor-neutral **MCP stdio**. This document
covers an **optional OpenAI-specific relay** for ChatGPT or another supported
OpenAI client that cannot execute a local/SSH MCP subprocess.

The relay is not a generic AI transport. Other model providers can use a
standard stdio MCP connection or a separately developed, tested adapter.

For Oracle Solaris, follow the [local installation guide](solaris-portability.md#run-your-own-openai-tunnel)
for the account-owned layout and foreground tunnel command.

## Supported layout

Set the following explicitly in the ignored host inventory:

```yaml
dcmcp_user: EXISTING_NONROOT_ACCOUNT
dcmcp_transport: openai_tunnel
```

In this mode the role stages a pinned Desktop Commander/Node bundle **and**
an official pinned `tunnel-client` binary. After manual configuration and
activation, a systemd system service runs under that existing Linux account.
The unit connects outbound to `https://api.openai.com` on HTTPS 443, not to a
public inbound MCP endpoint. No privilege or user is created by Ansible.

**Breaking-installation notice:** The unified release manifest format uses
`schema: 2` with `transport: openai_tunnel`; older releases are not accepted.
Do not attempt in-place upgrades on a legacy live installation. Plan manual
service deactivation, uninstall and fresh install, preserving keys as needed.

## Installation

1. Prepare your Ansible controller and inventory following the main README.
   Specify `dcmcp_transport: openai_tunnel` explicitly, and choose an existing
   non-root account. Ensure this account has the desired privileges.
2. Install the versioned bundle, without starting the service:

   ```bash
   .venv/bin/ansible-playbook playbooks/install.yml
   ```

3. In the runtime account's own shell, copy both sample configuration files.
   Ansible never overwrites active secrets or Desktop Commander settings:

   ```bash
   umask 077
   cp -n "/usr/local/share/desktop-commander-mcp/$(id -un)/tunnel.yaml.example" \
     "$HOME/.config/desktop-commander-mcp/tunnel.yaml"
   cp -n "/usr/local/share/desktop-commander-mcp/$(id -un)/desktop-commander.json.example" \
     "$HOME/.claude-server-commander/config.json"
   chmod 600 "$HOME/.config/desktop-commander-mcp/tunnel.yaml" \
     "$HOME/.claude-server-commander/config.json"
   vi "$HOME/.config/desktop-commander-mcp/tunnel.yaml"
   ```

   Create `$HOME/.config/desktop-commander-mcp/runtime.key` as an owned
   `0600` **regular file** with the OpenAI runtime API key. Do not use an
   administrative key, put keys into inventory, or expose secrets on process
   command lines. Keep both config directories private (`0700`). The YAML
   references `runtime.key` through `file:`; provide a unique provisioned
   tunnel ID. The accompanying sample/configuration.md documents expected
   fields and file modes.

4. The operator must already have the correct OpenAI account/workspace tunnel
   eligibility, registered tunnel and narrowly scoped runtime credentials.
   Use the [OpenAI dashboard](https://platform.openai.com/settings/organization/tunnels)
   to check permissions and register the tunnel. Installation alone never
   grants OpenAI-side authorization.
5. Run the offline preflight and then activate from an **independent** SSH
   or console session:

   ```bash
   .venv/bin/ansible-playbook playbooks/preflight.yml
   .venv/bin/ansible-playbook playbooks/activate.yml
   ```

The installed unit is `desktop-commander-mcp@USER.service`. Activation
validates private files and release checksums, enables/starts the service,
and waits for readiness from the listener owned by the managed process.
Readiness does **not** prove that remote agents have successfully listed
or invoked tools; test an actual tool call from the authorized client.

## Monitoring, diagnostics and lifecycle

```bash
sudo systemctl status desktop-commander-mcp@USER.service
sudo journalctl -u desktop-commander-mcp@USER.service -n 100 --no-pager
.venv/bin/ansible-playbook playbooks/monitor-enable.yml
.venv/bin/ansible-playbook playbooks/monitor-disable.yml
.venv/bin/ansible-playbook playbooks/deactivate.yml
```

- `playbooks/upgrade.yml` is intended for **running, supported-format** OpenAI
  daemon installations only. It stops the old daemon, swaps the verified
  release and checks readiness. It is **not** a migration command.
- `playbooks/uninstall.yml` stops the service, removes per-user helpers/units,
  and retains manually owned config/credentials and shared release bundles.
- `scripts/doctor.py` and the optional timer perform read-only local checks.
  Neither can prove remote OpenAI-side authorization.
- Avoid automatic restarts while a long-running MCP operation is underway.
  If activation fails, the role can restore the prior selector but deliberately
  leaves the service stopped for diagnosis; it does not claim a healthy rollback.
- Each simultaneously active OpenAI tunnel needs its own provisioned tunnel ID,
  account config and health port. Run Ansible operations sequentially.
- On SELinux hosts, the role restores standard file contexts without disabling
  enforcement; site-specific denials require independent diagnosis.

See [security](security.md), [validation history](validation.md) and
[upstream notes](upstream.md).
