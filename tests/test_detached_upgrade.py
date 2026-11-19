"""Detached upgrades use a root transient unit, never password files or remote SSH."""
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/validate-local-inventory.py"
loader = importlib.util.spec_from_file_location("local_inventory_validator", SCRIPT)
module = importlib.util.module_from_spec(loader)
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    loader.loader.exec_module(module)
finally:
    sys.path.remove(str(ROOT / 'scripts'))


class DetachedUpgradeTests(unittest.TestCase):
    def test_local_only_inventory_validation(self):
        good = '''all:
  children:
    mcp_servers:
      hosts:
        localhost:
          ansible_connection: local
          ansible_python_interpreter: /usr/bin/python3
          dcmcp_user: mcp_operator
'''
        self.assertTrue(module.is_local_only_inventory(good))
        example = (ROOT / 'inventory/local.example.yml').read_text().replace(
            'REPLACE_WITH_EXISTING_ACCOUNT', 'mcp_operator')
        self.assertTrue(module.is_local_only_inventory(example))
        for invalid in (good.replace('local\n', 'ssh\n'),
                        good.replace('localhost:', 'remote:'),
                        good.replace('mcp_operator', 'root'),
                        good.replace('mcp_operator', 'REPLACE_WITH_EXISTING_LINUX_ACCOUNT'),
                        good.replace('        localhost:', '        localhost:\n          ansible_host: example.net'),
                        good.replace('  children:', '  vars:\n    key: value\n  children:'),
                        'not: yaml: valid:',
                        good + 'all: {children: {mcp_servers: {hosts: {localhost: {dcmcp_user: root}}}}}\n',
                        good.replace('          dcmcp_user: mcp_operator', '          dcmcp_user: mcp_operator\n          dcmcp_user: root'),
                        good.replace('dcmcp_user: mcp_operator', 'dcmcp_user: &identity mcp_operator\n          ansible_user: *identity')):
            with self.subTest(invalid=invalid):
                self.assertFalse(module.is_local_only_inventory(invalid))

    def test_privilege_boundary_and_no_persisted_sudo_password(self):
        launch = (ROOT / "scripts/upgrade-detached.sh").read_text()
        runner = (ROOT / "scripts/upgrade-runner.sh").read_text()
        self.assertIn('sudo -v', launch)
        self.assertIn('sudo -n systemd-run', launch)
        self.assertIn('--setenv=HOME=/root', launch)
        self.assertNotIn('--property=User=', launch)
        self.assertIn('$(id -u) != 0', runner)
        self.assertIn('validate-local-inventory.py', launch)
        self.assertIn('validate-local-inventory.py', runner)
        for bad in ('SUDO_ASKPASS', 'sudo -S', 'ask-become-pass', 'ANSIBLE_BECOME_PASS'):
            self.assertNotIn(bad, launch + runner)


if __name__ == "__main__":
    unittest.main()
