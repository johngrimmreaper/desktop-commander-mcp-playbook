"""User selection must be explicit, never inferred from host/SSH identity."""
from pathlib import Path
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/dcmcp"


class ExplicitRuntimeUserTests(unittest.TestCase):
    def test_no_implicit_user_in_default_vars_or_example_inventories(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertNotIn("dcmcp_user", defaults)
        for filename in ("local.example.yml", "hosts.example.yml"):
            inventory = yaml.safe_load((ROOT / "inventory" / filename).read_text())
            for host in inventory["all"]["children"]["mcp_servers"]["hosts"].values():
                self.assertNotIn("dcmcp_user", host)

    def test_first_role_task_rejects_missing_user_before_mutation(self):
        tasks = yaml.safe_load((ROLE / "tasks/context.yml").read_text())
        self.assertIn("ansible.builtin.assert", tasks[0])
        self.assertIn("dcmcp_user", str(tasks[0]))
        self.assertIn("untracked inventory/hosts.yml", tasks[0]["ansible.builtin.assert"]["fail_msg"])

    def test_direct_preflight_cli_requires_explicit_user(self):
        result = subprocess.run(
            [sys.executable, str(ROLE / "files/preflight.py"), "--release-only",
             "--release", "/nonexistent-release"],
            capture_output=True, text=True, check=False, timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("--user", result.stderr)
        self.assertIn("required", result.stderr)


if __name__ == "__main__":
    unittest.main()
