"""Guard against a whitespace error causing an Ansible zero-host no-op."""
import importlib.util
import sys
from pathlib import Path
import unittest

import yaml

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
            'REPLACE_WITH_EXISTING_ACCOUNT', 'mcp_operator')
        remote = (ROOT / 'inventory/hosts.example.yml').read_text().replace(
            'REPLACE_WITH_EXISTING_ACCOUNT', 'mcp_operator').replace(
            'REPLACE_WITH_SERVER_ADDRESS', 'example.net').replace(
            'REPLACE_WITH_SSH_USER', 'operator')
        self.assertTrue(module.valid_inventory(local))
        self.assertTrue(module.valid_inventory(remote))
        for broken in (local.replace('          dcmcp_user:', '\tdcmcp_user:'),
                       local.replace('          dcmcp_user: mcp_operator\n', ''),
                       local.replace('mcp_operator', 'root'),
                       local.replace('mcp_servers:', 'bad_group:'),
                       local.replace('localhost:', 'wronghost:'),
                       local.replace('mcp_operator', 'REPLACE_WITH_EXISTING_ACCOUNT'),
                       remote.replace('example.net', 'REPLACE_WITH_SERVER_ADDRESS'),
                       '---\nall: {}\n',
                       local + 'all: {children: {mcp_servers: {hosts: {localhost: {dcmcp_user: root}}}}}\n',
                       local.replace('          dcmcp_user: mcp_operator', '          dcmcp_user: mcp_operator\n          dcmcp_user: root'),
                       local.replace('dcmcp_user: mcp_operator', 'dcmcp_user: &identity mcp_operator\n          ansible_user: *identity')):
            with self.subTest(broken=broken):
                self.assertFalse(module.valid_inventory(broken))

    def test_versioned_system_python_for_local_solaris(self):
        local = (ROOT / 'inventory/local.example.yml').read_text().replace(
            'REPLACE_WITH_EXISTING_ACCOUNT', 'mcp_operator')
        self.assertTrue(module.valid_inventory(local))
        host = yaml.safe_load(local)['all']['children']['mcp_servers']['hosts']['localhost']
        self.assertEqual(host['dcmcp_transport'], 'stdio')
        self.assertEqual(host['ansible_python_interpreter'], '{{ ansible_playbook_python }}')
        document = yaml.safe_load(local)
        host = document['all']['children']['mcp_servers']['hosts']['localhost']
        host['ansible_python_interpreter'] = '/usr/bin/python3.13'
        self.assertTrue(module.valid_inventory(yaml.safe_dump(document)))
        for interpreter in ('python3.13', '/tmp/python3.13', '/usr/bin/python3.13 -E',
                            '/usr/bin/python3x13', '', None):
            with self.subTest(interpreter=interpreter):
                document = yaml.safe_load(local)
                host = document['all']['children']['mcp_servers']['hosts']['localhost']
                host['ansible_python_interpreter'] = interpreter
                self.assertFalse(module.valid_inventory(yaml.safe_dump(document)))


if __name__ == '__main__':
    unittest.main()
