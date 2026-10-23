"""Installed audit validates only pinned metadata and never mutates the host."""
from pathlib import Path
import importlib.util
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
path = ROOT / 'scripts/test-installed-readonly.py'
spec = importlib.util.spec_from_file_location('installed_readonly', path)
module = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(ROOT / 'scripts'))
try:
    spec.loader.exec_module(module)
finally:
    sys.path.remove(str(ROOT / 'scripts'))


class InstalledReadOnlyTests(unittest.TestCase):
    def test_expected_release_and_manifest_are_version_scoped(self):
        defaults = {'dcmcp_desktop_version': '0.3.1',
                    'dcmcp_desktop_revision': 'a' * 40, 'dcmcp_lock_blob': 'b' * 40,
                    'dcmcp_node_version': '24.21.0', 'dcmcp_tunnel_version': '0.0.16',
                    'dcmcp_node_checksums': {'x86_64': 'c' * 64},
                    'dcmcp_tunnel_checksums': {'x86_64': 'd' * 64}}
        name = module.expected_release(defaults, 'x86_64')
        self.assertEqual(name, 'dc-0.3.1-aaaaaaaaaaaa-node-24.21.0-tunnel-0.0.16-x86_64')
        manifest = module.expected_manifest(defaults, 'x86_64')
        self.assertEqual(manifest['node_sha256'], 'c' * 64)
        self.assertEqual(manifest['tunnel_sha256'], 'd' * 64)
        self.assertEqual(manifest['architecture'], 'x86_64')

    def test_no_host_mutation_commands(self):
        source = path.read_text()
        for prohibited in ('sudo', 'os.unlink(', 'os.remove(', 'os.rename(',
                           'systemctl restart', 'systemctl start', 'systemctl stop',
                           'ansible-playbook', 'write_text(', 'open("w")'):
            self.assertNotIn(prohibited, source)
        self.assertIn('require_native_host(allow_rpm=True)', source)
        self.assertIn('capture_output=True', source)


if __name__ == '__main__':
    unittest.main()
