"""Two account identities must never share writable tunnel instance state."""
import importlib.util
from pathlib import Path
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/dcmcp"
SPEC = importlib.util.spec_from_file_location("dcmcp_multi_preflight", ROLE / "files/preflight.py")
pf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pf
SPEC.loader.exec_module(pf)


class MultiuserIsolationTests(unittest.TestCase):
    def test_runtime_contexts_have_disjoint_writable_paths(self):
        a = pf.Context("alice", 1001, Path("/home/alice"),
                       Path("/home/alice"), Path("/home/alice"))
        b = pf.Context("bob", 1002, Path("/home/bob"),
                       Path("/home/bob"), Path("/home/bob"))
        for name in ("home", "config", "key", "desktop_config", "helpers", "unit", "current"):
            with self.subTest(name=name):
                self.assertNotEqual(getattr(a, name), getattr(b, name))
        self.assertEqual(a.current.parent, a.prefix / "instances/alice")
        self.assertEqual(b.current.parent, b.prefix / "instances/bob")

    def test_instance_scoped_role_resources(self):
        defaults = (ROLE / "defaults/main.yml").read_text()
        for resource in ("dcmcp_home: \"{{ dcmcp_account_home }}\"",
                         "dcmcp_helpers:", "dcmcp_instance_dir:",
                         "dcmcp_current:", "dcmcp_activation_stamp:",
                         "dcmcp_monitor_service:", "dcmcp_monitor_timer:",
                         "dcmcp_runtime_dir:"):
            self.assertIn(resource, defaults)
        self.assertNotIn("/var/lib/desktop-commander-mcp/home", defaults)
        activation = (ROLE / "tasks/activate.yml").read_text()
        self.assertNotIn("/var/lib/desktop-commander-mcp/activation.sha256", activation)
        self.assertNotIn('"{{ dcmcp_prefix }}/current"', activation)
        for file in ("tasks/activate.yml", "tasks/upgrade-guard.yml",
                     "tasks/uninstall.yml", "tasks/monitor-disable.yml"):
            self.assertIn("dcmcp_", (ROLE / file).read_text())
        self.assertIn("{{ dcmcp_user }}", (ROLE / "templates/run.py.j2").read_text())
        self.assertIn("{{ dcmcp_runtime_dir }}", (ROLE / "templates/run.py.j2").read_text())
        self.assertIn("{{ dcmcp_health_port }}", (ROLE / "templates/tunnel.yaml.example.j2").read_text())

    def test_uninstall_preserves_shared_releases_and_other_users(self):
        uninstall = yaml.safe_load((ROLE / "tasks/uninstall.yml").read_text())
        targets = [item for task in uninstall for item in task.get("loop", [])]
        self.assertIn("{{ dcmcp_instance_dir }}", targets)
        self.assertIn("{{ dcmcp_helpers }}", targets)
        self.assertNotIn("{{ dcmcp_prefix }}", targets)
        self.assertNotIn("/var/cache/desktop-commander-mcp", targets)
        for name in ("activate", "deactivate", "install", "uninstall", "upgrade"):
            self.assertEqual(yaml.safe_load((ROOT / f"playbooks/{name}.yml").read_text())[0]["serial"], 1)


if __name__ == "__main__":
    unittest.main()
