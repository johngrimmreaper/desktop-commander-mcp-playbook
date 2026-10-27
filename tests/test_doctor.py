"""The doctor is read-only and never outputs secrets or follows arbitrary URLs."""
from pathlib import Path
import os
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

from scripts import doctor


class DoctorTests(unittest.TestCase):
    def test_sensitive_files_require_owner_mode_regular_and_no_hardlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "runtime.key"
            path.write_text("example-secret")
            path.chmod(0o600)
            self.assertTrue(doctor.private_file(path, os.getuid()))
            self.assertFalse(doctor.private_file(path, os.getuid() + 100000))
            path.chmod(0o644)
            self.assertFalse(doctor.private_file(path, os.getuid()))
            path.chmod(0o600)
            (Path(temporary) / "link").hardlink_to(path)
            self.assertFalse(doctor.private_file(path, os.getuid()))
            path.unlink()
            self.assertFalse(doctor.private_file(path, os.getuid()))

    def test_health_endpoint_must_be_local_and_valid(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "tunnel.yaml"
            for addr, expect in (("127.0.0.1:8787", "127.0.0.1:8787"),
                                 ("127.0.0.1:1", None),
                                 ("0.0.0.0:8787", None),
                                 ("api.openai.com:443", None),
                                 ("127.0.0.1:99999", None),
                                 ("127.0.0.1:0", None)):
                path.write_text(f'health:\n  listen_addr: "{addr}"\n')
                self.assertEqual(doctor.health_address(path), expect)
            path.write_text("api_key: sk-example\nhealth: [invalid")
            self.assertIsNone(doctor.health_address(path))

    def test_owned_readiness_fails_closed_on_missing_or_untrusted_helper(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "readiness.py"
            path.write_text("print('ready')\n")
            path.chmod(0o666)
            with (mock.patch.object(doctor, "READINESS", path),
                  mock.patch.object(doctor, "probe") as probe):
                self.assertFalse(doctor.managed_readiness("127.0.0.1:8787"))
                probe.assert_not_called()
            path.unlink()
            with mock.patch.object(doctor, "READINESS", path):
                self.assertFalse(doctor.managed_readiness("127.0.0.1:8787"))

    def test_diagnostics_use_managed_checker_not_arbitrary_http_200(self):
        with mock.patch.object(doctor, "managed_readiness", return_value=False):
            self.assertFalse(doctor.managed_readiness("127.0.0.1:8787"))
        self.assertNotIn("urllib", Path(doctor.__file__).read_text())
        self.assertIn("--listen-addr", Path(doctor.__file__).read_text())

    def test_diagnostics_reads_desktop_config_from_account_home(self):
        account = SimpleNamespace(pw_uid=os.getuid(), pw_dir="/home/example")
        checked = []
        def record(path, _uid):
            checked.append(path)
            return True
        with (mock.patch.object(doctor, "unit_state", return_value={"User": "example"}),
              mock.patch.object(doctor.pwd, "getpwnam", return_value=account),
              mock.patch.object(doctor, "private_file", side_effect=record),
              mock.patch.object(doctor, "health_address", return_value=None),
              mock.patch.object(doctor, "selected_release", return_value=None),
              mock.patch.object(doctor, "probe", return_value=None)):
            result = doctor.diagnose()
        self.assertTrue(result["private_config"])
        self.assertIn(Path("/home/example/.claude-server-commander/config.json"), checked)
        self.assertNotIn(doctor.HOME / ".claude-server-commander/config.json", checked)

    def test_diagnostics_only_emit_boolean_or_known_selinux_status(self):
        with (mock.patch.object(doctor, "unit_state", return_value={
                  "LoadState": "loaded", "ActiveState": "active", "UnitFileState": "enabled",
                  "MainPID": "123", "User": "nonexistent-example-user", "ControlGroup": ""}),
              mock.patch.object(doctor, "selected_release", return_value="dc-version"),
              mock.patch.object(doctor, "probe", return_value="Enforcing")):
            output = doctor.diagnose()
        self.assertFalse(output["runtime_user"])
        self.assertFalse(output["private_config"])
        self.assertFalse(output["readiness"])
        self.assertEqual(output["selinux"], "Enforcing")
        self.assertTrue(all(isinstance(v, bool) for k, v in output.items() if k != "selinux"))


if __name__ == "__main__":
    unittest.main()
