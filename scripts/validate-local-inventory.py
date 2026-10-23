#!/usr/bin/env python3
"""Require a local-only inventory before launching a root detached upgrade."""
import argparse
from pathlib import Path
import re
import sys

import yaml


def is_local_only_inventory(source):
    try:
        doc = yaml.safe_load(source)
        if not isinstance(doc, dict) or set(doc) != {"all"}:
            return False
        all_group = doc["all"]
        if set(all_group) != {"children"}:
            return False
        servers = all_group["children"]
        if set(servers) != {"mcp_servers"}:
            return False
        group = servers["mcp_servers"]
        if set(group) != {"hosts"}:
            return False
        hosts = group["hosts"]
        if not isinstance(hosts, dict) or set(hosts) != {"localhost"}:
            return False
        values = hosts["localhost"]
        return (isinstance(values, dict)
                and values.get("ansible_connection") == "local"
                and values.get("ansible_python_interpreter") == "/usr/bin/python3"
                and not any(key in values for key in
                            ("ansible_host", "ansible_user", "ansible_become_password"))
                and isinstance(values.get("dcmcp_user"), str)
                and bool(re.fullmatch(r"[a-z_][a-z0-9_-]*", values["dcmcp_user"]))
                and values["dcmcp_user"] != "root")
    except (TypeError, KeyError, yaml.YAMLError):
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("inventory", type=Path)
    args = parser.parse_args()
    try:
        content = args.inventory.read_text()
    except OSError:
        content = ""
    if not is_local_only_inventory(content):
        print("Refusing detached upgrade: use one localhost with a local connection, "
              "system Python and explicitly selected non-root dcmcp_user. "
              "Use SSH/console for remote inventories.", file=sys.stderr)
        return 2
    print("Detached upgrade inventory: local host verified (no secrets displayed).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
