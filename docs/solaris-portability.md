# Solaris portability: prerequisites before implementation

**Status (2026-11-16): analysis only.** Neither this Ansible role nor the
pinned Desktop Commander release has been built or tested on Solaris.
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
| `roles/dcmcp/files/preflight.py` | `/usr/bin/rg`, `/bin/bash`, `/usr/bin/sudo` and the Linux native library probes are mandatory. Their paths and Solaris behavior need verified alternatives, without weakening ownership/security checks. |
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
