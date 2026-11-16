"""Guard the vendor-neutral installation boundary without mutating a native host."""
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
ROLE = ROOT / "roles/dcmcp"
TASKS = ROLE / "tasks"


class TransportModesTests(unittest.TestCase):
    def test_role_default_preserves_old_deployments_and_examples_are_neutral(self):
        defaults = yaml.safe_load((ROLE / "defaults/main.yml").read_text())
        self.assertEqual(defaults["dcmcp_transport"], "openai_tunnel")
        for name in ("hosts", "local"):
            inventory = yaml.safe_load((ROOT / f"inventory/{name}.example.yml").read_text())
            hosts = inventory["all"]["children"]["mcp_servers"]["hosts"]
            host = next(iter(hosts.values()))
            self.assertEqual(host["dcmcp_transport"], "stdio")

    def test_tunnel_download_and_installed_service_are_optional(self):
        release = yaml.safe_load((TASKS / "release.yml").read_text())
        main = yaml.safe_load((TASKS / "main.yml").read_text())
        blocks = [task for task in release if "block" in task]
        self.assertEqual(len(blocks), 1)
        tunnel_ops = [task for task in blocks[0]["block"]
                      if task["name"] in (
                          "Download the official tunnel client with its pinned release asset digest",
                          "Create the tunnel release directory",
                          "Extract the verified tunnel client bundle",
                          "Ensure the released client is executable",
                          "Check the tunnel client version without starting a daemon")]
        self.assertEqual(len(tunnel_ops), 5)
        self.assertTrue(all(task["when"] == "dcmcp_transport == 'openai_tunnel'"
                            for task in tunnel_ops))
        for label in ("Install the OpenAI tunnel supervisor launcher",
                      "Install the OpenAI managed daemon readiness helper",
                      "Install the OpenAI tunnel systemd unit without starting it"):
            task = next(task for task in main if task["name"] == label)
            self.assertEqual(task["when"], "dcmcp_transport == 'openai_tunnel'")

    def test_stdio_activation_and_preflight_do_not_contact_vendor(self):
        activate = yaml.safe_load((TASKS / "activate-stdio.yml").read_text())
        self.assertFalse(any("ansible.builtin.systemd_service" in task for task in activate))
        select = next(task for task in activate if "select-release.py" in str(task))
        self.assertIn("{{ dcmcp_target_release }}", select["ansible.builtin.command"]["argv"])
        preflight = yaml.safe_load((TASKS / "preflight.yml").read_text())
        check = next(task for task in preflight if task["name"].startswith("Validate vendor-neutral"))
        self.assertIn("--stdio", check["ansible.builtin.command"]["argv"])
        self.assertEqual(check["when"], "dcmcp_transport == 'stdio'")

    def test_transport_conversion_is_fail_closed(self):
        main = yaml.safe_load((TASKS / "main.yml").read_text())
        safeguards = [task for task in main if task["name"].startswith("Prevent")
                      and ("transport" in task["name"] or "conversion" in task["name"])]
        self.assertTrue(any("'stdio'" in str(task.get("when")) for task in safeguards))
        self.assertTrue(any("'openai_tunnel'" in str(task.get("when"))
                            for task in safeguards))

    def test_stdio_configuration_excludes_openai_secret_material(self):
        companion = (ROLE / "templates/configuration-stdio.md.j2").read_text()
        self.assertIn("{{ dcmcp_helpers }}/mcp-child", companion)
        main = yaml.safe_load((TASKS / "main.yml").read_text())
        examples = next(task for task in main if task["name"].startswith("Install commented"))
        self.assertIn("configuration-stdio.md.j2", str(examples["loop"]))
        self.assertIn("item.dest != 'tunnel.yaml.example'", examples["when"])


if __name__ == "__main__":
    unittest.main()
