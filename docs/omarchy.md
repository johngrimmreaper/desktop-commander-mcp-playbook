# Omarchy Linux / Arch Linux deployment notes

**Status:** Arch backend validated on one native headless Omarchy Slim
Server KVM VM (2026-11-09). Pinned native installation, production preflight,
systemd activation/readiness, and live ChatGPT-originated MCP execution all
passed. See `docs/validation.md` for anonymized evidence, limitations and
untested scenarios. One host does not establish universal compatibility.

Omarchy is Arch-based, and has historically reported `ID=arch` in
`/etc/os-release`. Ansible reports this family as `Archlinux`; our backend
intentionally covers native Arch as well as Omarchy. It does not depend on
Hyprland, Wayland, the AUR, an AUR helper, or the user-session systemd manager.
For `openai_tunnel`, the production unit remains a root-managed systemd
service, running under the explicitly selected non-root Linux account. In
`stdio` mode, no long-running service or OpenAI runtime key is needed.

## Operator preparation in the new VM

1. Verify the OS identity (`cat /etc/os-release`), native systemd PID 1
   (`cat /proc/1/comm`), `x86_64` or `aarch64` architecture (`uname -m`), and
   the existing non-root account (`id`); do not assume Omarchy's login name.
2. Review Arch News and Omarchy updates. Complete a supported full update
   (`sudo pacman -Syu`) independently of the installer. Do not attempt a
   `pacman -Sy` partial upgrade. The installer does **not** update pacman sync
   databases or perform upgrades. Resolve any stale-mirror/keyring issues
   before running it.
3. Prepare the controller's Python/venv prerequisites on the current fully
   updated Arch VM. For a local controller, the ordinary official packages
   `python`, `python-pip` and `git` may be installed using `pacman -S --needed`.
4. From the checkout, install pinned Ansible development requirements and
   its collection using:

   ```bash
   python -m venv .venv
   .venv/bin/python -m pip install -r requirements-dev.txt
   .venv/bin/ansible-galaxy collection install -r collections/requirements.yml
   cp -n inventory/local.example.yml inventory/hosts.yml
   vi inventory/hosts.yml
   .venv/bin/python scripts/validate-inventory.py
   .venv/bin/python scripts/check.py
   ```

5. Replace the `dcmcp_user` placeholder with the actual existing account.
   Keep `dcmcp_transport: stdio` for vendor-neutral direct MCP, or explicitly
   choose `openai_tunnel` to reproduce the verified OpenAI setup.
   Run `playbooks/install.yml` from an independent SSH/console session with
   the required sudo permissions. If necessary, use `--ask-become-pass`.
   Installation stages a release but deliberately does not activate the daemon.
6. For OpenAI mode, copy and manually edit the private tunnel/key/desktop files
   described in the main README, run `playbooks/preflight.yml`, and explicitly
   activate with `playbooks/activate.yml` from an independent session. Never
   check real tunnel credentials into Git or reuse an active tunnel ID on a
   second host.
7. For OpenAI mode, verify systemd service, local `/readyz`, read-only doctor,
   journal, and an actual ChatGPT-originated MCP tool call. For stdio mode,
   verify a real MCP tool call from an authorized stdio client instead. Record real Omarchy results in
   `docs/validation.md` only after running them.

## Backend design and constraints

- Uses pinned `community.general.pacman` from `collections/requirements.yml`,
  not an invented pacman subprocess wrapper or an AUR helper.
- Installs the official repository packages `ca-certificates`, `git`, `xz`,
  `unzip`, `python`, `python-yaml`, `ripgrep`, `base-devel`, `libatomic` via
  `state: present`; does not run `-Sy`, `-Syu` or update desktop components.
- Reuses pinned private Node binaries, source verification, file ownership,
  immutable releases and offline preflight. The OpenAI mode additionally pins
  a tunnel client and installs a systemd daemon; stdio does neither.
- Arch uses explicit `/usr/bin/python3` for systemd launchers; no SELinux
  relabeling is attempted on the standard Arch installation.
- The destructive native integration test suites remain Ubuntu-only. The
  offline tests and synthetic host guards can run on Arch/Omarchy.
- Arch can change quickly. Test the pinned Node binary, Git/npm build,
  optional native dependencies, libc compatibility, and tunnel connectivity
  on the actual Omarchy VM before calling the backend validated.
