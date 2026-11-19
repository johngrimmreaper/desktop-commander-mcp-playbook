# Local Desktop Commander on Oracle Solaris

The source build and stdio test passed on Oracle Solaris 11.4.90 CBE x86-64
on 2026-11-19. The VM used IPS Node.js 22.15.1, npm 10.9.2, the locked
SunOS esbuild 0.27.2 binary, and Sharp's WebAssembly build. Ripgrep 14.1.1
built natively. An MCP client initialized, listed 25 tools and found a
fixture file with `list_directory`.

A local run of `playbooks/install.yml` on 2026-11-19 with
`dcmcp_transport=openai_tunnel` completed on that VM with
`ok=38 changed=16 failed=0`. Ansible built the native tunnel client v0.0.16
with Go 1.27.0, ran its version check, and passed the local MCP smoke test
before selecting the release. The foreground tunnel connected and served
MCP requests through that VM. The SMF boot service is configured separately
through `playbooks/activate.yml`.

## Run Ansible locally on the Solaris VM

Install the Python modules through the Solaris publisher. Ansible Core 2.21
needs a supported controller interpreter, so select Python 3.13 explicitly.

```sh
sudo pkg install \
    library/python/pip-313 \
    library/python/cryptography-313 \
    library/python/pyyaml-313 \
    library/python/jinja2-313

/usr/bin/python3.13 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-controller.txt
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml
```

Copy the shared local inventory if you have not set it up.

```sh
cp -i inventory/local.example.yml inventory/hosts.yml
vi inventory/hosts.yml
```

Select an existing non-root `dcmcp_user`. Run Ansible as that account.
`ansible_connection: local` and the controller Python interpreter apply to
the local target. Keep `dcmcp_transport: stdio` for a local MCP client, or set
`dcmcp_transport: openai_tunnel` for your own OpenAI Secure MCP Tunnel.

Inspect the OS packages if needed, then install the native tools.

```sh
.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/solaris-probe.yml

sudo pkg install runtime/nodejs/nodejs-22 developer/rust/rustc developer/rust/cargo
node --version
npm --version
cargo --version
```

The Node 22 package for CBE .90 depends on system libraries from that release.
Use `pkg install -nv` to check the package plan before installing on an older
image. The playbook uses Cargo to build ripgrep when it creates a release.
At runtime, Desktop Commander uses the resulting `rg` executable.

Install from the checked-out playbook as the selected account.

```sh
.venv/bin/python scripts/validate-inventory.py inventory/hosts.yml
.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/install.yml
```

A successful run creates a versioned release under
`~/.local/share/desktop-commander-mcp/releases`. The installer verifies
the source commit and lockfile, builds with Node.js from the VM, and uses an
isolated configuration to test stdio discovery and a file listing. It then
points `current` at the release. When the pins match, subsequent runs check
and reuse the existing release.

Review and copy the Desktop Commander example to enable the local launcher.

```sh
dcmcp_dir="$HOME/.local/share/desktop-commander-mcp"
(umask 077
 cp -i "$dcmcp_dir/examples/desktop-commander.json.example" \
    "$HOME/.claude-server-commander/config.json"
)
```

The example turns telemetry off and permits file and command operations under
the runtime account. Review its allowed directories and blocked commands
before sharing access. Point a stdio MCP client at
`$HOME/.local/share/desktop-commander-mcp/mcp-child`.

## Run your own OpenAI tunnel

When `openai_tunnel` is selected, the installer also checks out the pinned
tunnel-client source, builds it with the checksum-pinned Solaris Go archive,
and checks the resulting binary's version and source revision. Go is used
in staging for this build. The release keeps the client executable.

Provision the tunnel and a runtime key using the OpenAI account as described
in [OpenAI tunnel setup](openai-tunnel.md). Use the Solaris-generated YAML
example for the child command and local health address. Fill in your tunnel
ID and store the key separately in `runtime.key`, using modes `0700` for the
directory and `0600` for both files.

```sh
dcmcp_dir="$HOME/.local/share/desktop-commander-mcp"
tunnel_dir="$HOME/.config/desktop-commander-mcp"
(umask 077
 mkdir -p "$tunnel_dir"
 chmod 700 "$tunnel_dir"
 cp -i "$dcmcp_dir/examples/tunnel.yaml.example" "$tunnel_dir/tunnel.yaml"
)
vi "$tunnel_dir/tunnel.yaml"
```

After placing the runtime key and both active configuration files, run
`activate.yml` locally as the same account used for installation. The playbook
checks the installed release and configuration offline. It uses sudo for the
SMF manifest and service commands. The manifest runs the tunnel as the selected
account and starts it on future boots. The client reads the key from its
existing file reference.

Stop any foreground client for the same tunnel before activating the service.
Run the playbook in a local shell or an independent SSH session.

```sh
.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/activate.yml \
    -e dcmcp_transport=openai_tunnel
```

The playbook checks the configured loopback health and readiness endpoints.
To check status and find the SMF log, run the following commands.

```sh
svc="svc:/site/desktop-commander-mcp-$(id -un):default"
svcs -l "$svc"
svcs -L "$svc"
```

Run activation again with `-e dcmcp_restart=true` after changing the tunnel
configuration, rotating the runtime key or selecting a new release. To stop
the service and disable boot activation, run `sudo svcadm disable -s "$svc"`.
The active configuration and key live outside the release directory.

References: [Ansible Core support matrix](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html),
[Oracle public Solaris repository](http://pkg.oracle.com/solaris/release/en/catalog.shtml),
[Go downloads and checksums](https://go.dev/dl/).
