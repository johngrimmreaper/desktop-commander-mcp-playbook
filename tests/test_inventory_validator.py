"""Guard against a whitespace error causing an Ansible zero-host no-op."""
import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'scripts/validate-inventory.py'
spec = importlib.util.spec_from_file_location('inventory_validator', path)
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    spec.loader.exec_module(module)
finally:
    sys.path.remove(str(ROOT / 'scripts'))


class InventoryValidatorTests(unittest.TestCase):
    def test_valid_local_and_remote_inventory(self):
        local = (ROOT / 'inventory/local.example.yml').read_text().replace(
            'REPLACE_WITH_EXISTING_LINUX_ACCOUNT', 'mcp_operator')
        remote = (ROOT / 'inventory/hosts.example.yml').read_text().replace(
            'REPLACE_WITH_EXISTING_LINUX_ACCOUNT', 'mcp_operator').replace(
            'REPLACE_WITH_SERVER_ADDRESS', 'example.net').replace(
            'REPLACE_WITH_SSH_USER', 'operator')
        self.assertTrue(module.valid_inventory(local))
        self.assertTrue(module.valid_inventory(remote))
        for broken in (local.replace('          dcmcp_user:', '\tdcmcp_user:'),
                       local.replace('          dcmcp_user: mcp_operator\n', ''),
                       local.replace('mcp_operator', 'root'),
                       local.replace('mcp_servers:', 'bad_group:'),
                       local.replace('localhost:', 'wronghost:'),
                       local.replace('mcp_operator', 'REPLACE_WITH_EXISTING_LINUX_ACCOUNT'),
                       remote.replace('example.net', 'REPLACE_WITH_SERVER_ADDRESS'),
                       '---\nall: {}\n',
                       local + 'all: {children: {mcp_servers: {hosts: {localhost: {dcmcp_user: root}}}}}\n',
                       local.replace('          dcmcp_user: mcp_operator', '          dcmcp_user: mcp_operator\n          dcmcp_user: root'),
                       local.replace('dcmcp_user: mcp_operator', 'dcmcp_user: &identity mcp_operator\n          ansible_user: *identity')):
            with self.subTest(broken=broken):
                self.assertFalse(module.valid_inventory(broken))


if __name__ == '__main__':
    unittest.main()
