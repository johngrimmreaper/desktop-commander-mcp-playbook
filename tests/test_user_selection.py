"""User selection must be explicit, never inferred from host/SSH identity."""
from pathlib import Path
import re
import subprocess
import sys
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/dcmcp"


class ExplicitRuntimeUserTests(unittest.TestCase):
    def test_explicit_space_indented_account_placeholder_in_examples(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertNotIn("dcmcp_user", defaults)
        for filename, preceding_key in (
            ("local.example.yml", "ansible_python_interpreter"),
            ("hosts.example.yml", "ansible_user"),
        ):
            with self.subTest(filename=filename):
                example = (ROOT / "inventory" / filename).read_text()
                self.assertNotIn("\t", example, "YAML examples must use spaces, not tabs")
                lines = example.splitlines()
                account_line = "          dcmcp_user: REPLACE_WITH_EXISTING_ACCOUNT"
                self.assertEqual(lines.count(account_line), 1)
                index = lines.index(account_line)
                self.assertTrue(lines[index - 1].startswith(f"          {preceding_key}: "))
                inventory = yaml.safe_load(example)
                hosts = inventory["all"]["children"]["mcp_servers"]["hosts"]
                self.assertEqual(len(hosts), 1)
                user = next(iter(hosts.values()))["dcmcp_user"]
                self.assertEqual(user, "REPLACE_WITH_EXISTING_ACCOUNT")
                # This is a configuration prompt, never an implicit runtime identity.
                self.assertIsNone(re.fullmatch(r"[a-z_][a-z0-9_-]*", user))

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
