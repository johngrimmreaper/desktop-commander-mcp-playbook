"""Inventories must not silently shadow a runtime identity via YAML features."""
from pathlib import Path
import unittest

import yaml

from scripts.inventory_yaml import load_inventory


class InventoryYamlTests(unittest.TestCase):
    def test_reject_duplicates_aliases_merges_tabs_and_oversize(self):
        for payload in (
                'host: a\nhost: b\n',
                'all:\n  children:\n    mcp_servers:\n      hosts:\n        localhost: {}\n        localhost: {dcmcp_user: root}\n',
                'login: &account mcp_operator\ndcmcp_user: *account\n',
                'x: &base {dcmcp_user: mcp_operator}\ny:\n  <<: *base\n',
                'x: {<<: {dcmcp_user: mcp_operator}}\n',
                'all:\n\tdcmcp_user: mcp_operator\n',
                '---\na: 1\n---\nb: 2\n',
                'a: ' + 'x' * 262145,
                '{[not valid yaml',
        ):
            with self.subTest(payload=payload[:80]), self.assertRaises(yaml.YAMLError):
                load_inventory(payload)

    def test_example_inventories_pass_after_manual_placeholder_replacement(self):
        root = Path(__file__).resolve().parents[1]
        for filename in ('local.example.yml', 'hosts.example.yml'):
            text = (root / 'inventory' / filename).read_text()
            self.assertIn('all', load_inventory(text))


if __name__ == '__main__':
    unittest.main()
