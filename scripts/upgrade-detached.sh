#!/usr/bin/env bash
# Launch the upgrade as a separate transient systemd service, not a child of MCP.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
# Only a single explicitly local target may be upgraded by the detached root
# controller. A root systemd service cannot borrow a user's SSH credentials.
"$root/.venv/bin/python" "$root/scripts/validate-local-inventory.py" \
  "$root/inventory/hosts.yml"
if ! systemctl is-active --quiet desktop-commander-mcp.service; then
  echo 'Production MCP is inactive. Use install/preflight/activate instead.' >&2
  exit 2
fi
# Prompt for sudo once *before* the transient unit is launched. The detached
# root service does not need a password, credential file or a controlling TTY.
# Noninteractive MCP sessions without cached/passwordless sudo must use an
# independent terminal to authenticate. Never stage a password for the unit.
if ! sudo -v; then
  echo 'Sudo authentication failed; run from an independent SSH/console session.' >&2
  exit 2
fi
unit="dcmcp-upgrade-$(date -u +%Y%m%dT%H%M%SZ)-$$"
sudo -n systemd-run \
  --unit="$unit" \
  --collect \
  --property=UMask=0077 \
  --property=WorkingDirectory="$root" \
  --setenv=HOME=/root \
  --setenv=PYTHONDONTWRITEBYTECODE=1 \
  --setenv="ANSIBLE_CONFIG=$root/ansible.cfg" \
  /usr/bin/bash "$root/scripts/upgrade-runner.sh"
printf 'Upgrade unit: %s.service\n' "$unit"
printf 'Check results: sudo journalctl -u %s.service --no-pager -n 100\n' "$unit"
