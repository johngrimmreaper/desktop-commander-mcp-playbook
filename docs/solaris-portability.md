# Solaris portability: prerequisites before implementation

**Status (2026-11-18): local controller preparation and read-only probe.**
Native Desktop Commander installation and OpenAI tunnel activation on Solaris
remain pending native dependency tests and service backend implementation.
Do not remove the existing native-Linux guard just to make an install appear to
succeed. Preserve the Linux operation and tests while developing a Solaris
backend in a separate branch.

## What is now independent of the AI provider

- The `stdio` path needs only a compatible MCP client, an authorized runtime
  user and a launcher exposing Desktop Commander on stdin/stdout.
- The OpenAI runtime key, tunnel YAML, client download, systemd daemon,
  readiness endpoint and `/proc`-based readiness checker belong to the optional
  `openai_tunnel` adapter, not to standard MCP.
- An MCP client on another machine may run a command through ordinary SSH;
  the playbook does not implement an arbitrary remote-provider relay.

## Linux assumptions to replace or isolate

| Current code | Required Solaris investigation |
| --- | --- |
| `roles/dcmcp/tasks/context.yml` | Linux distribution facts, native systemd/PID 1 check, `systemd-detect-virt`, `/proc/1/comm` and hard-coded `service_mgr == systemd` must not gate a Solaris-specific stdio backend. |
| `roles/dcmcp/tasks/packages.yml` | Provide a native Solaris package backend and map required tools using existing, trusted OS repositories; do not assume apt, dnf, pacman, glibc or GNU file locations. |
| `roles/dcmcp/tasks/release.yml` | Node download is `node-...-linux-...`; esbuild is `@esbuild/linux-*`, sharp uses platform native bindings, and `mv -T` is GNU-specific. Verify supported Solaris builds and toolchain **before** enabling installation. |
| `roles/dcmcp/files/preflight.py` | `/usr/bin/rg`, `/bin/bash` and Linux native library probes are required; sudo is optional for the MCP runtime. Their paths and Solaris behavior need verified alternatives, without weakening ownership/security checks. |
| `roles/dcmcp/files/select-release.py` | Check `os.O_DIRECTORY`, atomic symlink replacement and directory fsync support on the selected Solaris/Python filesystem. |
| `roles/dcmcp/templates/mcp-child.j2` | POSIX-shell launch is a promising portable boundary; review `/usr/bin/id`, Node executable paths, user HOME and the optional Linux `/run/user/UID` D-Bus logic. |
| `playbooks/{activate,deactivate,uninstall,upgrade}.yml` | Service lifecycle uses systemd and needs Solaris-specific adapters only if a long-lived daemon is actually selected. Stdio does not need an always-on service. |
| `roles/dcmcp/files/readiness.py` | Reads Linux `/proc/PID/net/tcp`, `/proc/PID/fd` and systemctl state; it is not a portable readiness checker for Solaris. Keep it confined to Linux OpenAI mode. |
| `scripts/doctor.py`, native tests | Current diagnostics and integration harness assume Linux service management; add explicit Solaris checks and real VM acceptance evidence. |

## Acceptance sequence for a future Solaris branch

1. Identify the exact Solaris release and architecture, Python interpreter,
   package sources, C/C++ toolchain, native Node support and `sharp`/`esbuild`
   availability. Avoid assuming Linux-compatible prebuilt binaries work.
2. Build Desktop Commander and run protocol tests from a non-root Solaris user
   **without** adding a vendor-specific tunnel.
3. Implement distro-specific installation/ownership/preflight and safe release
   selection; keep existing Linux tasks intact and test both paths separately.
4. Validate idempotence, installer failure recovery, permissions, stdio
   initialization, tools listing and one safe tool call over an authenticated
   SSH connection. Only then assess optional background service management.

Do not claim Solaris compatibility based only on Ansible YAML syntax checks.

## Run Ansible locally on the Solaris VM

Use the Solaris VM as both the Ansible controller and its managed host. The
local connection executes modules directly under the selected interpreter.

The supplied Oracle Solaris 11.4.81.193.1 x86 CBE inspection on 2026-11-18
reported Python 3.13.1, Python 3.11.11, GCC 14.2, Git 2.48.1, GNU Make,
and sudo access for the existing `mcp_operator` account. The default
`/usr/bin/python3` selected Python 3.11.11. Ansible Core 2.21 requires
controller Python 3.12 through 3.14, so select `/usr/bin/python3.13`
explicitly.

From a checkout of this branch, install the Python modules from the configured
Solaris publisher. These packages provide the native cryptography and YAML
extensions for Python 3.13.

```sh
sudo pkg install \
    library/python/pip-313 \
    library/python/cryptography-313 \
    library/python/pyyaml-313 \
    library/python/jinja2-313

/usr/bin/python3.13 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -r requirements-controller.txt
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml
.venv/bin/ansible --version
```

The virtual environment can read the Solaris Python packages. Its pip
installation writes into the virtual environment. The minimal
`requirements-controller.txt` contains the Ansible and inventory-parser
requirements. The development requirements additionally install the lint
tools used for repository checks.

Configure the local inventory as the existing runtime user.

```sh
cp -i inventory/local.example.yml inventory/hosts.yml
vi inventory/hosts.yml
```

Replace `REPLACE_WITH_EXISTING_ACCOUNT` with the existing runtime
account, such as `mcp_operator`. The shared inventory selects
`ansible_connection: local`, `{{ ansible_playbook_python }}`, and the standard
`stdio` transport. The interpreter follows the Python environment running
Ansible. Select the existing runtime account explicitly.
For OpenAI Secure MCP Tunnel, set `dcmcp_transport: openai_tunnel`
in the private inventory.

Verify local Ansible execution and collect the native dependency information.

```sh
.venv/bin/python scripts/validate-inventory.py inventory/hosts.yml
.venv/bin/ansible -i inventory/hosts.yml mcp_servers -m ansible.builtin.ping
.venv/bin/ansible-playbook -i inventory/hosts.yml playbooks/solaris-probe.yml
```

The probe reads the release, architecture, account, executable locations,
Node version, package publishers, and installable Node, Rust, ripgrep, and
libvips packages. It uses the regular account and makes read-only queries.
A successful probe establishes local controller execution. Native Desktop
Commander installation and OpenAI tunnel activation still require the
Solaris backends listed above and VM acceptance tests.

The supplied CBE package query offered Node.js 20.18.2 and found no installable
ripgrep or libvips package. The pinned Desktop Commander source requires
Node.js 22.12 or newer. Its Node runtime, image library, and search runtime
therefore need native dependency verification before the install role can
support this CBE image.

References for the controller bootstrap and dependency checks are the
[Ansible Core support matrix](https://docs.ansible.com/projects/ansible/latest/reference_appendices/release_and_maintenance.html),
[Ansible Python environment guidance](https://docs.ansible.com/projects/ansible/latest/reference_appendices/faq.html),
and [Oracle's public Solaris package catalog](http://pkg.oracle.com/solaris/release/en/catalog.shtml).
