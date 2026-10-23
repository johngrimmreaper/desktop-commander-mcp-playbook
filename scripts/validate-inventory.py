#!/usr/bin/env python3
"""Catch invalid or empty host inventories before Ansible silently skips work."""
from pathlib import Path
import re
import sys

import yaml

from inventory_yaml import load_inventory

ROOT = Path(__file__).resolve().parents[1]


def valid_inventory(source):
    try:
        doc = load_inventory(source)
        hosts = doc["all"]["children"]["mcp_servers"]["hosts"]
        if not isinstance(hosts, dict) or not hosts:
            return False
        for name, host in hosts.items():
            if not isinstance(host, dict):
                return False
            user = host.get("dcmcp_user")
            if not isinstance(user, str) or user == "root" or not re.fullmatch(
                    r"[a-z_][a-z0-9_-]*", user):
                return False
            if host.get("ansible_connection") == "local":
                if name != "localhost" or host.get("ansible_python_interpreter") != "/usr/bin/python3":
                    return False
            elif (not isinstance(host.get("ansible_host"), str)
                  or not host.get("ansible_host", "").strip()
                  or not isinstance(host.get("ansible_user"), str)
                  or not host.get("ansible_user", "").strip()
                  or any("REPLACE_WITH" in host[key] for key in ("ansible_host", "ansible_user"))):
                return False
        return True
    except (TypeError, KeyError, yaml.YAMLError):
        return False


def main():
    path = Path(sys.argv[1]) if len(sys.argv) == 2 else ROOT / "inventory/hosts.yml"
    try:
        content = path.read_text()
    except OSError:
        content = ""
    if not valid_inventory(content):
        print("Invalid MCP inventory: check YAML spaces, mcp_servers hosts, connection "
              "settings and an explicitly selected non-root dcmcp_user. "
              "No installation attempted.", file=sys.stderr)
        return 2
    print("MCP inventory validated (account and host values not displayed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
