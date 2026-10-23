"""Static contracts for Ubuntu, RHEL, Fedora and Arch Linux backends."""
from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "roles/dcmcp/tasks"


class DistroPackagesTests(unittest.TestCase):
    def test_package_backends_are_explicit_and_fedora_uses_dnf5(self):
        tasks = yaml.safe_load((TASKS / "packages.yml").read_text())
        apt = [task for task in tasks if "ansible.builtin.apt" in task]
        dnf = [task for task in tasks if "ansible.builtin.dnf" in task]
        dnf5 = [task for task in tasks if "ansible.builtin.dnf5" in task]
        pacman = [task for task in tasks if "community.general.pacman" in task]
        self.assertEqual((len(apt), len(dnf), len(dnf5), len(pacman)), (1, 1, 1, 1))
        arch = pacman[0]["community.general.pacman"]
        self.assertEqual(arch["state"], "present")
        self.assertIs(arch["update_cache"], False)
        self.assertNotIn("upgrade", arch)  # Mutually exclusive with name; defaults false.
        self.assertIn("Archlinux", pacman[0]["when"])
        self.assertTrue({"python", "python-yaml", "base-devel", "libatomic", "ripgrep"} <= set(arch["name"]))
        self.assertEqual(dnf[0]["ansible.builtin.dnf"]["use_backend"], "dnf4")
        for task, distro in ((apt[0], "Ubuntu"), (dnf[0], "RedHat"),
                             (dnf5[0], "Fedora")):
            self.assertIn(distro, task["when"])
            for package in ("ca-certificates", "git", "unzip", "ripgrep"):
                module = next(key for key in task if key.startswith("ansible.builtin."))
                self.assertIn(package, task[module]["name"])
        for task in (dnf[0], dnf5[0]):
            module = next(key for key in task if key.startswith("ansible.builtin."))
            self.assertTrue({"gcc", "gcc-c++", "make", "libatomic", "python3-pyyaml",
                             "python3-libselinux", "libselinux-utils"}
                            <= set(task[module]["name"]))

    def test_pacman_collection_is_pinned_and_arch_is_not_a_partial_upgrade(self):
        requirements = yaml.safe_load((ROOT / "collections/requirements.yml").read_text())
        self.assertIn({"name": "community.general", "version": "13.5.0"},
                      requirements["collections"])
        tasks = yaml.safe_load((TASKS / "packages.yml").read_text())
        pacman = next(task["community.general.pacman"] for task in tasks
                      if "community.general.pacman" in task)
        self.assertEqual(pacman["state"], "present")
        self.assertFalse(pacman["update_cache"])
        self.assertNotIn("upgrade", pacman)
        self.assertNotIn("extra_args", pacman)
        self.assertNotIn("executable", pacman)  # Use official pacman, not an AUR helper.

    def test_rhel_requires_manually_prepared_trusted_repositories(self):
        tasks = yaml.safe_load((TASKS / "packages.yml").read_text())
        self.assertTrue(any("rpm" in str(t.get("ansible.builtin.command", ""))
                            and "ripgrep" in str(t) for t in tasks))
        self.assertTrue(any("RHEL 10 needs the ripgrep RPM" in str(t) for t in tasks))
        forbidden = {"epel-release", "subscription-manager", "setenforce", "setsebool"}
        self.assertTrue(not any(item in (TASKS / "packages.yml").read_text()
                                for item in forbidden))

    def test_rendered_service_launchers_on_each_distribution(self):
        template = (ROOT / "roles/dcmcp/templates/desktop-commander-mcp.service.j2").read_text()
        engine = Environment(undefined=StrictUndefined)
        variables = {
            "dcmcp_user": "alice", "dcmcp_gid": "1234",
            "dcmcp_workdir": "/home/alice",
            "dcmcp_home": "/var/lib/desktop-commander-mcp/home",
            "dcmcp_prefix": "/opt/desktop-commander-mcp",
            "dcmcp_helpers": "/usr/local/libexec/desktop-commander-mcp",
        }
        launcher = "/usr/local/libexec/desktop-commander-mcp/run"
        for distro in ("Ubuntu", "RedHat", "Fedora", "Archlinux"):
            with self.subTest(distribution=distro):
                unit = engine.from_string(template).render(**variables,
                        ansible_facts={"distribution": distro})
                expected = launcher if distro == "Ubuntu" else "/usr/bin/python3 " + launcher
                self.assertIn("ExecStart=" + expected + "\n", unit)
                self.assertIn("User=alice\n", unit)
                self.assertIn("WorkingDirectory=/home/alice\n", unit)
                self.assertNotIn("User=mcp_operator", unit)

    def test_selinux_handling_is_limited_to_managed_paths(self):
        tasks = yaml.safe_load((TASKS / "main.yml").read_text())
        releases = yaml.safe_load((TASKS / "release.yml").read_text())
        relabels = [item for item in tasks + releases
                    if "restorecon" in str(item.get("ansible.builtin.command", ""))]
        self.assertEqual(len(relabels), 2)
        for item in relabels:
            args = item["ansible.builtin.command"]["argv"]
            self.assertEqual(args[:2], ["/usr/bin/env", "restorecon"])
            self.assertIn("dcmcp_selinux_mode", str(item["when"]))
            self.assertNotIn("/home", str(args))


if __name__ == "__main__":
    unittest.main()
