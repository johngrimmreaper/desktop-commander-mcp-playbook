"""Offline checks must use the invoking Python environment, not shell activation."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from scripts import check


class OfflineCheckRunnerTests(unittest.TestCase):
    def test_venv_tools_override_path_and_are_used_by_every_check(self):
        with tempfile.TemporaryDirectory() as temporary:
            venv = Path(temporary) / "venv"
            scripts = venv / "bin"
            scripts.mkdir(parents=True)
            for tool in ("ruff", "ansible-lint", "ansible-playbook"):
                path = scripts / tool
                path.write_text("#!/bin/sh\nexit 0\n")
                path.chmod(0o700)
            python = scripts / "python"
            python.write_text("#!/bin/sh\nexit 0\n")
            python.chmod(0o700)

            with (mock.patch.object(check.sys, "executable", str(python)),
                  mock.patch.object(check.sys, "prefix", str(venv)),
                  mock.patch.object(check.sys, "base_prefix", "/usr"),
                  mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}),
                  mock.patch.object(check.subprocess, "run", return_value=mock.Mock(returncode=0))
                  as run):
                self.assertEqual(check.main(), 0)

            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(commands[0][0], str(python))
            self.assertEqual(commands[1][0], str(scripts / "ruff"))
            self.assertEqual(commands[2][0], str(scripts / "ansible-lint"))
            self.assertEqual(len(commands), 3 + len(list((check.ROOT / "playbooks").glob("*.yml"))))
            for command in commands[3:]:
                self.assertEqual(command[0], str(scripts / "ansible-playbook"))
            for call in run.call_args_list:
                env = call.kwargs["env"]
                self.assertEqual(env["PATH"].split(os.pathsep)[0], str(scripts))
                self.assertEqual(call.kwargs["cwd"], check.ROOT)

    def test_missing_venv_tool_does_not_silently_use_global_tool(self):
        with tempfile.TemporaryDirectory() as temporary:
            venv = Path(temporary)
            scripts = venv / "bin"
            scripts.mkdir()
            with (mock.patch.object(check.sys, "executable", str(scripts / "python")),
                  mock.patch.object(check.sys, "prefix", str(venv)),
                  mock.patch.object(check.sys, "base_prefix", "/usr"),
                  mock.patch.dict(os.environ, {"PATH": "/usr/bin:/bin"}),
                  mock.patch.object(check.subprocess, "run") as run):
                self.assertEqual(check.main(), 127)
            run.assert_not_called()

    def test_system_python_keeps_path_based_tools(self):
        with (mock.patch.object(check.sys, "prefix", "/usr"),
              mock.patch.object(check.sys, "base_prefix", "/usr"),
              mock.patch.object(check.shutil, "which", return_value="/usr/bin/ruff") as which):
            self.assertEqual(check.tool_executable("ruff"), "/usr/bin/ruff")
            which.assert_called_once_with("ruff")


if __name__ == "__main__":
    unittest.main()
