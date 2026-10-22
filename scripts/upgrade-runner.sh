#!/usr/bin/env bash
# Run outside the MCP systemd cgroup, typically via upgrade-detached.sh.
# Ansible activation may terminate every process inside the MCP unit.
set -euo pipefail

root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
cd "$root"
playbook="$root/.venv/bin/ansible-playbook"
inventory="$root/inventory/hosts.yml"
selector=/opt/desktop-commander-mcp/current
service=desktop-commander-mcp.service
export ANSIBLE_CONFIG="$root/ansible.cfg"

if [[ ! -x "$playbook" || ! -f "$inventory" || ! -L "$selector" ]]; then
  echo 'Upgrade prerequisites missing. No changes made.' >&2
  exit 2
fi
old_release=$(basename -- "$(readlink -f -- "$selector")")
if [[ ! "$old_release" =~ ^dc-[A-Za-z0-9._-]+$ ]]; then
  echo 'Unexpected original release ID. Refusing upgrade.' >&2
  exit 2
fi

printf 'Original release: %s\n' "$old_release"
if "$playbook" -i "$inventory" playbooks/upgrade.yml; then
  echo 'Upgrade completed and the Ansible-managed readiness check passed.'
  exit 0
fi

printf 'Upgrade failed. Checking the original runtime before recovery.\n' >&2
if systemctl is-active --quiet "$service" && \
   [[ "$(basename -- "$(readlink -f -- "$selector")")" == "$old_release" ]]; then
  echo 'Original daemon remains active and selected. No recovery restart needed.' >&2
  exit 1
fi

printf 'Attempting rollback to previously selected release %s.\n' "$old_release" >&2
if ! "$playbook" -i "$inventory" playbooks/preflight.yml \
  -e "dcmcp_target_release=$old_release"; then
  echo 'Rollback preflight failed; use SSH/console for manual recovery.' >&2
  exit 1
fi
if ! "$playbook" -i "$inventory" playbooks/activate.yml \
  -e "dcmcp_target_release=$old_release"; then
  echo 'Rollback activation failed; use SSH/console for manual recovery.' >&2
  exit 1
fi
if ! systemctl is-active --quiet "$service" || \
   [[ "$(basename -- "$(readlink -f -- "$selector")")" != "$old_release" ]]; then
  echo 'Rollback did not restore expected state; investigate via console.' >&2
  exit 1
fi
printf 'Original release restored and ready. Upgrade remains FAILED.\n' >&2
exit 1
