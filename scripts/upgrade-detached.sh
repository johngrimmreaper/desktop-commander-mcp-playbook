#!/usr/bin/env bash
# Launch the upgrade as a separate transient systemd service, not a child of MCP.
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
if ! systemctl is-active --quiet desktop-commander-mcp.service; then
  echo 'Production MCP is inactive. Use install/preflight/activate instead.' >&2
  exit 2
fi
sudo -n -v
unit="dcmcp-upgrade-$(date -u +%Y%m%dT%H%M%SZ)-$$"
sudo -n systemd-run \
  --unit="$unit" \
  --collect \
  --property=User="$(id -un)" \
  --property=Group="$(id -gn)" \
  --property=WorkingDirectory="$root" \
  --setenv="HOME=$HOME" \
  --setenv="ANSIBLE_CONFIG=$root/ansible.cfg" \
  /usr/bin/bash "$root/scripts/upgrade-runner.sh"
printf 'Upgrade unit: %s.service\n' "$unit"
printf 'Check results: sudo journalctl -u %s.service --no-pager -n 100\n' "$unit"
