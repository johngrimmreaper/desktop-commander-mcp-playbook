"""Config/permission integration tests use a private fake runtime, never a live tunnel."""
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import pwd
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "dcmcp_preflight", ROOT / "roles/dcmcp/files/preflight.py")
pf = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = pf
SPEC.loader.exec_module(pf)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        # Parent directories created by pathlib inherit the process umask.
        # Keep fixtures private even on an operator host with a permissive umask.
        original_umask = os.umask(0o077)
        self.addCleanup(os.umask, original_umask)
        self.temporary = tempfile.TemporaryDirectory(prefix="dcmcp-test-")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        tunnel_home = root / "tunnel-home"
        account_home = root / "account-home"
        tunnel_home.mkdir(mode=0o700)
        account_home.mkdir(mode=0o700)
        self.ctx = pf.Context(pwd.getpwuid(os.geteuid()).pw_name, os.geteuid(),
                              tunnel_home, tunnel_home, account_home,
                              root / "installation", root / "helpers", root / "unit.service")
        self.env = patch.dict(os.environ, {"HOME": str(tunnel_home)})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.ctx.config.parent.mkdir(parents=True, mode=0o700)
        self.ctx.desktop_config.parent.mkdir(mode=0o700)
        self.ctx.helpers.mkdir(mode=0o755)
        self.release = self.ctx.prefix / "releases/test-release"
        (self.release / "node/bin").mkdir(parents=True, mode=0o755)
        (self.release / "node/lib/node_modules/npm/bin").mkdir(parents=True)
        (self.release / "tunnel").mkdir()
        (self.release / "mcp/dist").mkdir(parents=True)
        self.manifest = {
            "schema": 1, "desktop_version": "0.2.52", "desktop_revision": "a" * 40,
            "lock_blob": "b" * 40, "node_version": "24.21.0", "node_sha256": "c" * 64,
            "tunnel_version": "0.0.16", "tunnel_sha256": "d" * 64,
            "architecture": os.uname().machine,
        }
        self.write(self.release / "release.json", json.dumps(self.manifest), 0o644)
        self.write(self.release / "mcp/package.json", '{"version":"0.2.52"}', 0o644)
        self.write(self.release / "mcp/dist/index.js", "// fixture only", 0o644)
        self.write(self.release / "node/lib/node_modules/npm/bin/npm-cli.js", "// fixture", 0o644)
        for binary in ("node/bin/node", "tunnel/tunnel-client"):
            self.write(self.release / binary, "#!/bin/sh\nexit 0\n", 0o755)
        # Host dependencies live in an isolated temporary directory, not /usr/bin.
        # The fake ownership checks already model this installation prefix as root-owned.
        test_bin = self.ctx.prefix / "fixture-system-bin"
        test_bin.mkdir(mode=0o755)
        self.system_executables = tuple(test_bin / name for name in ("rg", "bash", "sudo"))
        for binary in self.system_executables:
            self.write(binary, "#!/bin/sh\nexit 0\n", 0o755)
        for helper in ("preflight.py", "readiness.py", "run", "mcp-child"):
            self.write(self.ctx.helpers / helper, "# fixture only\n", 0o755)
        self.write(self.ctx.unit, "# fixture only\n", 0o644)
        self.tunnel = {
            "config_version": 2,
            "control_plane": {"base_url": "https://api.openai.com",
                              "tunnel_id": "tunnel_" + "e" * 32,
                              "api_key": "file:" + str(self.ctx.key)},
            "mcp": {"commands": [{"channel": "main",
                                 "command": str(self.ctx.helpers / "mcp-child")}],
                    "stdio_send_initialized_notification": False, "forward_trace_context": False,
                    "max_concurrent_requests": 10},
            "log": {"level": "info", "format": "json"},
            "health": {"listen_addr": "127.0.0.1:18787"},
            "admin_ui": {"open_browser": False, "allow_remote": False},
        }
        self.desktop = {
            "blockedCommands": [], "allowedDirectories": [], "defaultShell": "/bin/bash",
            "telemetryEnabled": False, "fileWriteLineLimit": 1000, "fileReadLineLimit": 1000,
            "pendingWelcomeOnboarding": False, "welcomeOnboardingEligible": False,
        }
        self.write(self.ctx.config, yaml.safe_dump(self.tunnel), 0o600)
        self.write(self.ctx.desktop_config, json.dumps(self.desktop), 0o600)
        # Deliberately synthetic and never sent to OpenAI.
        self.write(self.ctx.key, "sk-" + "Z" * 32 + "\n", 0o600)
        self.real_read = pf.read_file
        self.real_lstat = Path.lstat
        # Every negative case must start from a known-valid configuration.
        self.validate()

    @staticmethod
    def write(path, text, mode):
        path.write_text(text)
        path.chmod(mode)

    def fake_lstat(self, path, *args, **kwargs):
        info = self.real_lstat(path, *args, **kwargs)
        if path == self.ctx.prefix or self.ctx.prefix in path.parents:
            values = list(info)
            values[4] = 0  # Model immutable root-owned installation, not the runtime files.
            return os.stat_result(values)
        return info

    def installed_read(self, path, uid, **kwargs):
        # A non-root test user cannot chown fixtures to root. Only install files are stubbed.
        installed = (self.ctx.prefix in Path(path).parents
                     or self.ctx.helpers in Path(path).parents or Path(path) == self.ctx.unit)
        return self.real_read(path, self.ctx.uid if installed and uid == 0 else uid, **kwargs)

    def fake_probe(self, argv, _ctx, _release, cwd=None):
        if argv[0].endswith("/node") and argv[1:] == ["--version"]:
            return "v24.21.0"
        if argv[0].endswith("/tunnel-client"):
            return "tunnel-client v0.0.16"
        return ""

    def validate(self, runner=None):
        test = self
        def root_owned_lstat(path, *args, **kwargs):
            return test.fake_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", root_owned_lstat), \
                patch.object(pf, "read_file", side_effect=self.installed_read), \
                patch.object(pf, "REQUIRED_SYSTEM_EXECUTABLES", self.system_executables):
            return pf.validate(self.ctx, self.release, runner=runner or self.fake_probe)

    def assert_invalid(self, action):
        with self.assertRaises((pf.InvalidConfig, OSError)):
            action()

    def test_rendered_launcher_is_valid_python_and_example_is_strict_json(self):
        from jinja2 import Environment
        template = (ROOT / "roles/dcmcp/templates/run.py.j2").read_text()
        rendered = Environment().from_string(template).render(
            dcmcp_helpers=str(self.ctx.helpers), dcmcp_user=self.ctx.user,
            dcmcp_uid=self.ctx.uid, dcmcp_home=str(self.ctx.home),
            dcmcp_workdir=str(self.ctx.workdir),
            dcmcp_account_home=str(self.ctx.account_home),
            dcmcp_service="desktop-commander-mcp@alice.service",
            dcmcp_runtime_dir="desktop-commander-mcp-alice",
            dcmcp_current=str(self.ctx.current))
        compile(rendered, "rendered-run", "exec")
        example = (ROOT / "roles/dcmcp/templates/desktop-commander.json.example.j2").read_bytes()
        pf.validate_desktop(pf.parse_json(example))

    def test_rendered_mcp_child_uses_passwd_home_and_valid_shell(self):
        import shlex
        import subprocess
        from jinja2 import Environment
        engine = Environment()
        engine.filters["quote"] = shlex.quote
        template = (ROOT / "roles/dcmcp/templates/mcp-child.j2").read_text()
        rendered = engine.from_string(template).render(
            dcmcp_home=str(self.ctx.home), dcmcp_account_home=str(self.ctx.account_home),
            dcmcp_user=self.ctx.user, dcmcp_uid=self.ctx.uid,
            dcmcp_current=str(self.ctx.current))
        self.assertIn('"$(/usr/bin/id -u)" != "' + str(self.ctx.uid) + '"', rendered)
        self.assertIn("export HOME=" + shlex.quote(str(self.ctx.account_home)), rendered)
        self.assertIn(f"export XDG_RUNTIME_DIR=/run/user/{self.ctx.uid}", rendered)
        self.assertIn(f"unix:path=/run/user/{self.ctx.uid}/bus", rendered)
        result = subprocess.run(["/bin/sh", "-n"], input=rendered, text=True,
                                capture_output=True, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_desktop_config_uses_passwd_home_not_tunnel_home(self):
        self.assertEqual(self.ctx.account_home / ".claude-server-commander/config.json",
                         self.ctx.desktop_config)
        self.assertNotEqual(self.ctx.home, self.ctx.account_home)

    def test_complete_offline_preflight_and_repeat_are_stable(self):
        first = self.validate()
        self.assertRegex(first, r"^[0-9a-f]{64}$")
        self.assertEqual(first, self.validate())

    def use_stdio_manifest(self):
        manifest = {key: value for key, value in self.manifest.items()
                    if key not in ("tunnel_version", "tunnel_sha256")}
        manifest.update(schema=2, transport="stdio")
        self.write(self.release / "release.json", json.dumps(manifest), 0o644)
        return manifest

    def validate_stdio(self):
        test = self
        def root_owned_lstat(path, *args, **kwargs):
            return test.fake_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", root_owned_lstat), \
                patch.object(pf, "read_file", side_effect=self.installed_read), \
                patch.object(pf, "REQUIRED_SYSTEM_EXECUTABLES", self.system_executables):
            return pf.validate_stdio(self.ctx, self.release, runner=self.fake_probe)

    def test_vendor_neutral_stdio_needs_no_tunnel_credentials_or_binary(self):
        self.use_stdio_manifest()
        self.ctx.config.unlink()
        self.ctx.key.unlink()
        (self.release / "tunnel/tunnel-client").unlink()
        self.assertEqual(self.release, self.validate_stdio())
        self.assert_invalid(self.validate)  # OpenAI mode must not accept this bundle.

    def test_vendor_neutral_stdio_rejects_wrong_manifest_or_missing_config(self):
        self.assert_invalid(self.validate_stdio)  # No fallback to an OpenAI-only release.
        self.use_stdio_manifest()
        self.ctx.desktop_config.unlink()
        self.assert_invalid(self.validate_stdio)

    def test_vendor_neutral_stdio_rejects_missing_launcher(self):
        self.use_stdio_manifest()
        (self.ctx.helpers / "mcp-child").unlink()
        self.assert_invalid(self.validate_stdio)

    def test_runtime_key_rotation_changes_fingerprint(self):
        before = self.validate()
        self.write(self.ctx.key, "sk-" + "Y" * 32, 0o600)
        self.assertNotEqual(before, self.validate())

    def test_desktop_runtime_metadata_does_not_trigger_restart(self):
        before = self.validate()
        self.desktop["totalToolCalls"] = 123
        self.write(self.ctx.desktop_config, json.dumps(self.desktop), 0o600)
        self.assertEqual(before, self.validate())

    def test_missing_files_fail(self):
        for path in (self.ctx.config, self.ctx.desktop_config, self.ctx.key):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                path.unlink()
                self.assert_invalid(self.validate)
                path.write_bytes(original)
                path.chmod(0o600)

    def test_insecure_secret_modes_fail(self):
        for mode in (0o644, 0o640, 0o400, 0o666):
            with self.subTest(mode=mode):
                self.ctx.key.chmod(mode)
                self.assert_invalid(self.validate)
        self.ctx.key.chmod(0o600)

    def test_insecure_directory_mode_fails(self):
        self.ctx.config.parent.chmod(0o755)
        self.assert_invalid(self.validate)

    def test_group_writable_configuration_ancestor_fails(self):
        self.ctx.config.parent.parent.chmod(0o770)
        self.assert_invalid(self.validate)

    def test_key_symlink_is_rejected(self):
        other = self.ctx.home / "other.key"
        self.write(other, "sk-" + "Z" * 32, 0o600)
        self.ctx.key.unlink()
        self.ctx.key.symlink_to(other)
        self.assert_invalid(self.validate)

    def test_key_hardlink_is_rejected(self):
        other = self.ctx.home / "linked.key"
        os.link(self.ctx.key, other)
        self.assert_invalid(self.validate)

    def test_wrong_process_home_fails(self):
        with patch.dict(os.environ, {"HOME": "/different"}):
            self.assert_invalid(self.validate)

    def test_wrong_runtime_identity_fails(self):
        with patch.object(pf.os, "geteuid", return_value=self.ctx.uid + 1):
            self.assert_invalid(self.validate)

    def test_wrong_secret_owner_fails(self):
        real_fstat = os.fstat
        def wrong_owner(descriptor):
            info = real_fstat(descriptor)
            values = list(info)
            values[4] = self.ctx.uid + 1
            return os.stat_result(values)
        with patch.object(pf.os, "fstat", side_effect=wrong_owner):
            self.assert_invalid(self.validate)

    def test_placeholders_and_admin_keys_fail(self):
        values = ("", "REPLACE_WITH_RUNTIME_KEY", "sk-...", "sk-admin-" + "Q" * 32,
                  "sk-" + "X" * 25 + "\nsk-" + "Y" * 25, "sk-" + "X" * 25 + " ")
        for value in values:
            with self.subTest(value=value[:15]):
                self.write(self.ctx.key, value, 0o600)
                self.assert_invalid(self.validate)

    def test_invalid_tunnel_settings_fail(self):
        cases = (
            ("id placeholder", lambda c: c["control_plane"].update(
                tunnel_id="REPLACE_WITH_PROVISIONED_TUNNEL_ID")),
            ("sample id", lambda c: c["control_plane"].update(
                tunnel_id="tunnel_0123456789abcdef0123456789abcdef")),
            ("id shape", lambda c: c["control_plane"].update(tunnel_id="tunnel_ABC")),
            ("plaintext", lambda c: c["control_plane"].update(base_url="http://api.openai.com")),
            ("literal key", lambda c: c["control_plane"].update(api_key="sk-" + "Z" * 32)),
            ("foreign key path", lambda c: c["control_plane"].update(api_key="file:/tmp/key")),
            ("public health", lambda c: c["health"].update(listen_addr="0.0.0.0:8787")),
            ("privileged port", lambda c: c["health"].update(listen_addr="127.0.0.1:443")),
            ("unknown key", lambda c: c.update(cloudflared={"managed": True})),
            ("http binding", lambda c: c["mcp"].update(server_urls=["http://localhost/mcp"])),
            ("extra child", lambda c: c["mcp"]["commands"].append(
                {"channel": "other", "command": "/bin/sh"})),
            ("bad concurrency", lambda c: c["mcp"].update(max_concurrent_requests=True)),
            ("config bool", lambda c: c.update(config_version=True)),
            ("remote UI", lambda c: c["admin_ui"].update(allow_remote=True)),
            ("raw logging", lambda c: c["log"].update(http_raw_unsafe=True)),
        )
        for name, change in cases:
            with self.subTest(case=name):
                cfg = copy.deepcopy(self.tunnel)
                change(cfg)
                self.assert_invalid(lambda: pf.validate_tunnel(cfg, self.ctx))

    def test_yaml_duplicates_aliases_multiple_documents_and_bad_syntax_fail(self):
        for data in (b"config_version: 2\nconfig_version: 2",
                     b"x: &anchor 1\ny: *anchor", b"x: 1\n---\ny: 2", b"x: ["):
            with self.subTest(data=data):
                self.assert_invalid(lambda: pf.parse_yaml(data))

    def test_strict_json_rejects_comments_duplicates_trailing_commas_and_nan(self):
        for data in (b'{"x":1,}', b'{"x":1,"x":2}', b'{/*comment*/"x":1}', b'{"x":NaN}'):
            with self.subTest(data=data):
                self.assert_invalid(lambda: pf.parse_json(data))

    def test_shell_limits_and_directory_paths_fail(self):
        for mutate in (lambda c: c.update(defaultShell="/missing/shell"),
                       lambda c: c.update(fileReadLineLimit=True),
                       lambda c: c.update(allowedDirectories=["relative"]),
                       lambda c: c.update(allowedDirectories=["/missing/dir"]),
                       lambda c: c.update(pendingWelcomeOnboarding=True)):
            cfg = copy.deepcopy(self.desktop)
            mutate(cfg)
            self.assert_invalid(lambda: pf.validate_desktop(cfg))

    def test_version_or_dependency_probe_failure_fails(self):
        def wrong_node(argv, ctx, release, cwd=None):
            if argv[0].endswith("/node") and argv[1:] == ["--version"]:
                return "v18.20.0"
            return self.fake_probe(argv, ctx, release, cwd)
        self.assert_invalid(lambda: self.validate(wrong_node))
        def failed_dependency(_argv, _ctx, _release, cwd=None):
            raise pf.InvalidConfig("An installed dependency failed its compatibility probe.")
        self.assert_invalid(lambda: self.validate(failed_dependency))

    def test_immutable_release_validation_does_not_require_active_configuration(self):
        for path in (self.ctx.config, self.ctx.desktop_config, self.ctx.key):
            path.unlink()
        test = self
        def root_owned_lstat(path, *args, **kwargs):
            return test.fake_lstat(path, *args, **kwargs)
        with patch.object(Path, "lstat", root_owned_lstat), \
                patch.object(pf, "read_file", side_effect=self.installed_read), \
                patch.object(pf, "REQUIRED_SYSTEM_EXECUTABLES", self.system_executables):
            release, _manifest = pf.validate_release(self.ctx, self.release, self.fake_probe)
        self.assertEqual(self.release, release)
        self.assertFalse(self.ctx.config.exists())
        self.assertFalse(self.ctx.desktop_config.exists())
        self.assertFalse(self.ctx.key.exists())

    def test_missing_system_executable_fails_closed(self):
        # Even with isolated fixtures, the production rg path remains mandatory.
        self.assertIn(Path("/usr/bin/rg"), pf.REQUIRED_SYSTEM_EXECUTABLES)
        self.system_executables[0].unlink()
        self.assert_invalid(self.validate)

    def test_matching_manifest_does_not_hide_missing_runtime_binary(self):
        (self.release / "node/bin/node").unlink()
        self.assert_invalid(self.validate)

    def test_missing_entrypoint_fails(self):
        (self.release / "mcp/dist/index.js").unlink()
        self.assert_invalid(self.validate)

    def test_foreign_release_and_architecture_fail(self):
        self.manifest["architecture"] = "unsupported"
        self.write(self.release / "release.json", json.dumps(self.manifest), 0o644)
        self.assert_invalid(self.validate)
        self.assert_invalid(lambda: pf.validate_release(self.ctx, self.ctx.home, self.fake_probe))

    def test_environment_is_explicit_and_excludes_control_plane_key(self):
        with patch.dict(os.environ, {"CONTROL_PLANE_API_KEY": "must-not-be-inherited",
                                     "MCP_COMMAND": "/wrong", "OPENAI_ADMIN_KEY": "must-not-inherit"}):
            env = pf.runtime_environment(self.ctx, self.release)
        self.assertNotIn("CONTROL_PLANE_API_KEY", env)
        self.assertNotIn("MCP_COMMAND", env)
        self.assertNotIn("OPENAI_ADMIN_KEY", env)
        self.assertEqual(str(self.ctx.home), env["HOME"])

    def test_cli_errors_do_not_disclose_malformed_secret_text(self):
        sentinel = "sk-DO_NOT_LOG_THIS_SECRET_VALUE"
        self.write(self.ctx.config, "api_key: [" + sentinel, 0o600)
        error_output = io.StringIO()
        account = SimpleNamespace(pw_uid=self.ctx.uid, pw_dir=str(self.ctx.account_home))
        with patch.object(sys, "argv", ["preflight.py", "--user", self.ctx.user, "--home", str(self.ctx.home)]), \
                patch.object(pf.pwd, "getpwnam", return_value=account), \
                patch("sys.stderr", error_output):
            self.assertEqual(78, pf.main())
        self.assertNotIn(sentinel, error_output.getvalue())
        self.assertIn("Preflight failed:", error_output.getvalue())

    def test_overlarge_secret_fails(self):
        self.write(self.ctx.key, "sk-" + "X" * 9000, 0o600)
        self.assert_invalid(self.validate)

    def test_group_writable_release_fails(self):
        self.release.chmod(0o777)
        self.assert_invalid(self.validate)

    def test_runtime_config_stays_untouched_during_preflight(self):
        paths = (self.ctx.config, self.ctx.desktop_config, self.ctx.key)
        before = {str(path): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                  for path in paths}
        self.validate()
        after = {str(path): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                 for path in paths}
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
