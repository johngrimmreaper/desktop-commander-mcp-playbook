"""The safe synthetic-facts test can run on RPM; destructive tests stay Ubuntu-only."""
import subprocess
import unittest
from unittest import mock

from scripts import host


class NativeHostGuardTests(unittest.TestCase):
    @staticmethod
    def check(distro, version, *, allow_rpm=False, allow_arch=False, container_rc=1,
              pid1="systemd"):
        def read_text(path):
            if str(path) == "/etc/os-release":
                return f'ID={distro}\nVERSION_ID="{version}"\n'
            if str(path) == "/proc/1/comm":
                return pid1 + "\n"
            raise AssertionError(path)

        with (mock.patch.object(host.Path, "read_text", autospec=True,
                                side_effect=lambda self: read_text(self)),
              mock.patch.object(host.subprocess, "run",
                                return_value=subprocess.CompletedProcess([], container_rc))):
            host.require_native_host(allow_rpm=allow_rpm, allow_arch=allow_arch)

    def test_only_ubuntu_is_allowed_for_destructive_suites(self):
        self.check("ubuntu", "26.04")
        for distro, version in (("arch", "rolling"), ("rhel", "10.2"), ("fedora", "43"),
                                ("fedora", "44"), ("ubuntu", "24.04")):
            with self.subTest(distro=distro, version=version):
                with self.assertRaises(SystemExit):
                    self.check(distro, version)

    def test_safe_synthetic_facts_suite_accepts_role_supported_distributions(self):
        for distro, version in (("ubuntu", "26.04"), ("rhel", "10.0"),
                                ("rhel", "10.2"), ("fedora", "43"), ("fedora", "44")):
            with self.subTest(distro=distro, version=version):
                self.check(distro, version, allow_rpm=True)

    def test_arch_requires_explicit_safe_host_opt_in(self):
        with self.assertRaises(SystemExit):
            self.check("arch", "rolling", allow_rpm=True)
        self.check("arch", "rolling", allow_rpm=True, allow_arch=True)

    def test_unsupported_releases_and_non_native_hosts_are_rejected(self):
        for distro, version in (("rhel", "9.7"), ("fedora", "45"),
                                ("ubuntu", "24.04"), ("debian", "13")):
            with self.subTest(distro=distro):
                with self.assertRaises(SystemExit):
                    self.check(distro, version, allow_rpm=True)
        for kwargs in ({"container_rc": 0}, {"container_rc": 2},
                       {"pid1": "bash"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(SystemExit):
                    self.check("rhel", "10.2", allow_rpm=True, **kwargs)


if __name__ == "__main__":
    unittest.main()
