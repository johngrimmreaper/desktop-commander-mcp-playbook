#!/usr/bin/python3
"""Offline validation for this project's deliberately small upstream config surface."""
import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import pwd
import re
import socket
import stat
import subprocess
import sys

try:
    import yaml
except ImportError:
    print("Preflight failed: install the python3-yaml dependency.", file=sys.stderr)
    sys.exit(78)


class InvalidConfig(Exception):
    """Messages are fixed diagnostics: never include input values or parser exceptions."""


class UniqueLoader(yaml.SafeLoader):
    pass


def unique_mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if not isinstance(key, str) or key in result or key == "<<":
            raise InvalidConfig("YAML keys must be unique strings; merge keys are not supported.")
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_mapping)


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidConfig("JSON contains duplicate keys.")
        result[key] = value
    return result


@dataclass(frozen=True)
class Context:
    user: str
    uid: int
    home: Path
    workdir: Path
    account_home: Path
    prefix: Path = Path("/opt/desktop-commander-mcp")
    helpers: Path = None
    unit: Path = None

    def __post_init__(self):
        if self.helpers is None:
            object.__setattr__(self, "helpers", Path("/usr/local/libexec/desktop-commander-mcp") / self.user)
        if self.unit is None:
            object.__setattr__(self, "unit", Path(f"/etc/systemd/system/desktop-commander-mcp@{self.user}.service"))

    @property
    def current(self):
        return self.prefix / "instances" / self.user / "current"

    @property
    def config(self):
        return self.home / ".config/desktop-commander-mcp/tunnel.yaml"

    @property
    def key(self):
        return self.home / ".config/desktop-commander-mcp/runtime.key"

    @property
    def desktop_config(self):
        return self.account_home / ".claude-server-commander/config.json"


def require(condition, message):
    if not condition:
        raise InvalidConfig(message)


def absolute_path(value):
    require(isinstance(value, (str, Path)), "A path has the wrong type.")
    path = Path(value)
    require(path.is_absolute() and str(path) == os.path.normpath(str(path)),
            "Paths must be absolute and normalized.")
    require(".." not in path.parts, "Parent traversal is not allowed in a configured path.")
    return path


def safe_parents(path):
    for parent in reversed(path.parents):
        info = parent.lstat()
        require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode),
                "A configured path has a missing, linked or non-directory parent.")
        # Root-owned sticky /tmp is safe for private, owned test directories.
        sticky_root = info.st_uid == 0 and bool(info.st_mode & stat.S_ISVTX)
        require(not info.st_mode & 0o022 or sticky_root,
                "A configured path has a group/world-writable parent.")


def private_directory(path, uid):
    path = absolute_path(path)
    safe_parents(path)
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_uid == uid and stat.S_IMODE(info.st_mode) == 0o700,
            "Config and secret directories must be real, runtime-owned directories of mode 0700.")


def read_file(path, uid, private=False, limit=1_048_576):
    path = absolute_path(path)
    safe_parents(path)
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(descriptor)
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1,
                "Config, secret and manifest files must be regular files without links.")
        require(info.st_uid == uid, "A file has the wrong owner.")
        if private:
            require(stat.S_IMODE(info.st_mode) == 0o600,
                    "Active configs and runtime keys must have mode 0600.")
        else:
            require(not info.st_mode & 0o022, "An installed file is group/world-writable.")
        require(info.st_size <= limit, "A configuration or secret file exceeds its size limit.")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            data = stream.read(limit + 1)
        require(len(data) <= limit, "A configuration or secret file exceeds its size limit.")
        return data
    finally:
        os.close(descriptor)


def parse_yaml(data):
    try:
        text = data.decode("utf-8")
        for token in yaml.scan(text):
            require(not isinstance(token, (yaml.tokens.AliasToken, yaml.tokens.AnchorToken)),
                    "YAML aliases and anchors are not supported.")
        result = yaml.load(text, Loader=UniqueLoader)
    except (yaml.YAMLError, UnicodeError, RecursionError, TypeError, ValueError):
        raise InvalidConfig("Tunnel configuration must be one valid YAML document.") from None
    require(isinstance(result, dict), "Tunnel configuration must be a YAML mapping.")
    return result


def parse_json(data):
    try:
        result = json.loads(data, object_pairs_hook=unique_json,
                            parse_constant=lambda _value: (_ for _ in ()).throw(
                                InvalidConfig("Non-finite JSON numbers are not allowed.")))
    except (ValueError, UnicodeError, RecursionError):
        raise InvalidConfig("Desktop configuration or manifest is not strict JSON.") from None
    require(isinstance(result, dict), "JSON configuration must be an object.")
    return result


def no_placeholders(value, depth=0):
    require(depth <= 20, "Configuration nesting exceeds the supported depth.")
    if isinstance(value, str):
        require(not re.search(r"REPLACE_|CHANGEME|YOUR_[A-Z_]+|<[^>]+>|sk-\.\.\.",
                              value, re.IGNORECASE),
                "Configuration or key still contains a placeholder.")
        require(value != "tunnel_0123456789abcdef0123456789abcdef",
                "Replace the upstream sample tunnel ID with the provisioned ID.")
    elif isinstance(value, dict):
        for key, child in value.items():
            no_placeholders(key, depth + 1)
            no_placeholders(child, depth + 1)
    elif isinstance(value, list):
        for child in value:
            no_placeholders(child, depth + 1)


def mapping_keys(value, required, optional=()):
    require(isinstance(value, dict), "A YAML section must be a mapping.")
    require(set(required) <= set(value) <= set(required) | set(optional),
            "A YAML section has missing or unsupported fields.")


def validate_tunnel(cfg, ctx):
    mapping_keys(cfg, ("config_version", "control_plane", "mcp", "log", "health", "admin_ui"))
    require(type(cfg["config_version"]) is int and cfg["config_version"] == 2,
            "Use config_version 2 for the strict single-document upstream schema.")
    plane = cfg["control_plane"]
    mapping_keys(plane, ("base_url", "tunnel_id", "api_key"))
    require(plane["base_url"] == "https://api.openai.com",
            "This baseline requires the official HTTPS OpenAI control-plane host root.")
    require(isinstance(plane["tunnel_id"], str)
            and re.fullmatch(r"tunnel_[0-9a-f]{32}", plane["tunnel_id"]),
            "Tunnel ID must contain the tunnel_ prefix and 32 lowercase hexadecimal digits.")
    require(plane["api_key"] == "file:" + str(ctx.key),
            "Use the native file reference to the separate runtime.key file.")
    mcp = cfg["mcp"]
    mapping_keys(mcp, ("commands", "stdio_send_initialized_notification",
                      "forward_trace_context", "max_concurrent_requests"))
    require(mcp["commands"] == [{"channel": "main", "command": str(ctx.helpers / "mcp-child")}],
            "Use exactly one main stdio binding to the managed MCP child launcher.")
    for key in ("stdio_send_initialized_notification", "forward_trace_context"):
        require(type(mcp[key]) is bool, "MCP options must be YAML booleans.")
    require(type(mcp["max_concurrent_requests"]) is int
            and 1 <= mcp["max_concurrent_requests"] <= 100,
            "MCP concurrency must be an integer from 1 to 100.")
    mapping_keys(cfg["log"], ("level", "format"))
    require(cfg["log"]["level"] in ("info", "warn", "error")
            and cfg["log"]["format"] == "json",
            "Use info/warn/error JSON logging without raw HTTP logging.")
    mapping_keys(cfg["health"], ("listen_addr",))
    address = cfg["health"]["listen_addr"]
    require(isinstance(address, str)
            and re.fullmatch(r"127\.0\.0\.1:[0-9]{1,5}", address),
            "Health must listen on an explicit IPv4 loopback port.")
    port = int(address.rsplit(":", 1)[1])
    require(1024 <= port <= 65535, "Use a non-privileged health port from 1024 to 65535.")
    mapping_keys(cfg["admin_ui"], ("open_browser", "allow_remote"))
    require(cfg["admin_ui"]["open_browser"] is False
            and cfg["admin_ui"]["allow_remote"] is False,
            "Headless operation requires browser opening and remote admin UI disabled.")
    no_placeholders(cfg)
    return port


def validate_desktop(cfg):
    for key in ("blockedCommands", "allowedDirectories"):
        require(key in cfg and isinstance(cfg[key], list)
                and all(isinstance(item, str) and item and "\n" not in item for item in cfg[key]),
                "Desktop Commander command/directory settings must be arrays of strings.")
    shell = absolute_path(cfg.get("defaultShell", ""))
    require(shell.is_file() and os.access(shell, os.X_OK), "The configured shell is not executable.")
    require(type(cfg.get("telemetryEnabled")) is bool, "telemetryEnabled must be a JSON boolean.")
    for key in ("fileWriteLineLimit", "fileReadLineLimit"):
        require(type(cfg.get(key)) is int and 1 <= cfg[key] <= 1_000_000,
                "File line limits must be positive bounded integers.")
    for directory in cfg["allowedDirectories"]:
        path = absolute_path(directory)
        require(path.is_dir() and os.access(path, os.R_OK | os.X_OK),
                "An allowed directory is missing or inaccessible.")
    for key in ("pendingWelcomeOnboarding", "welcomeOnboardingEligible"):
        require(cfg.get(key) is False, "Disable the two welcome flags for headless operation.")
    # Additional metadata/counters written by upstream are allowed.
    no_placeholders(cfg)


def validate_key(data):
    try:
        key = data.decode("ascii")
        if key.endswith("\n"):
            key = key[:-1]
    except UnicodeError:
        raise InvalidConfig("The runtime key must contain one ASCII key.") from None
    no_placeholders(key)
    require(not re.match(r"sk-admin(?:[-_]|$)", key, re.IGNORECASE),
            "Administrative API keys are not allowed in the daemon.")
    require(re.fullmatch(r"sk-[A-Za-z0-9_-]{20,}", key) is not None,
            "The runtime key is empty, malformed or not a single supported runtime key.")
    return key


def runtime_environment(ctx, release):
    # Flags > environment > YAML upstream: build a clean, explicit environment.
    # The key is loaded natively by the tunnel only, and is not in the MCP child env.
    # Both tunnel and MCP child run within the selected account's actual HOME.
    return {
        "HOME": str(ctx.home), "USER": ctx.user, "LOGNAME": ctx.user,
        "SHELL": "/bin/bash", "PATH": str(release / "node/bin") + ":/usr/local/bin:/usr/bin:/bin",
        "NODE_ENV": "production", "LANG": "C.UTF-8",
    }


def probe(argv, ctx, release, cwd=None):
    try:
        result = subprocess.run(argv, stdin=subprocess.DEVNULL, capture_output=True,
                                text=True, timeout=25, check=False,
                                env=runtime_environment(ctx, release),
                                cwd=cwd or ctx.workdir)
    except (OSError, subprocess.SubprocessError, UnicodeError):
        raise InvalidConfig("An installed dependency probe could not complete.") from None
    require(result.returncode == 0, "An installed dependency failed its compatibility probe.")
    # Do not print captured stdout/stderr or exceptions.
    return result.stdout.strip()


# Core Desktop Commander dependencies. Sudo is intentionally not required:
# the selected runtime identity may have no administrative privileges at all.
# Tests replace these with isolated fixtures, never system files.
REQUIRED_SYSTEM_EXECUTABLES = (
    Path("/usr/bin/rg"), Path("/bin/bash"),
)


def validate_release(ctx, release, runner=probe):
    requested = absolute_path(release)
    if requested == ctx.current:
        info = requested.lstat()
        require(stat.S_ISLNK(info.st_mode) and info.st_uid == 0,
                "The current release must be a root-owned managed symbolic link.")
        release = requested.resolve(strict=True)
    else:
        release = requested
    require(release.parent == ctx.prefix / "releases"
            and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,180}", release.name),
            "The selected release is outside the managed release directory.")
    safe_parents(release)
    info = release.lstat()
    require(stat.S_ISDIR(info.st_mode) and not stat.S_ISLNK(info.st_mode)
            and info.st_uid == 0 and not info.st_mode & 0o022,
            "The installed release must be a real root-owned directory.")
    manifest_bytes = read_file(release / "release.json", 0)
    manifest = parse_json(manifest_bytes)
    require(type(manifest.get("schema")) is int and manifest["schema"] == 2,
            "Unsupported release manifest schema; reinstall using the current installer.")
    required = ("schema", "transport", "desktop_version", "desktop_revision",
                "lock_blob", "node_version", "node_sha256", "architecture")
    transport = manifest.get("transport")
    require(transport in ("stdio", "openai_tunnel"), "Unknown MCP transport in release.")
    if transport == "openai_tunnel":
        mapping_keys(manifest, required + ("tunnel_version", "tunnel_sha256"))
    else:
        mapping_keys(manifest, required)
    for key in (("desktop_version", "node_version", "tunnel_version")
                if transport == "openai_tunnel" else ("desktop_version", "node_version")):
        require(isinstance(manifest[key], str)
                and re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", manifest[key]),
                "Release versions are malformed.")
    for key in ("desktop_revision", "lock_blob"):
        require(isinstance(manifest[key], str) and re.fullmatch(r"[0-9a-f]{40}", manifest[key]),
                "A source integrity pin is malformed.")
    for key in (("node_sha256", "tunnel_sha256") if transport == "openai_tunnel"
                else ("node_sha256",)):
        require(isinstance(manifest[key], str) and re.fullmatch(r"[0-9a-f]{64}", manifest[key]),
                "An archive integrity pin is malformed.")
    require(manifest["architecture"] == os.uname().machine,
            "The release architecture does not match the host.")
    node_version = tuple(map(int, manifest["node_version"].split(".")))
    require(node_version[0] == 24 and node_version >= (22, 12, 0),
            "This project supports Node 24; Desktop Commander requires a modern Node runtime.")
    binaries = (release / "node/bin/node", *REQUIRED_SYSTEM_EXECUTABLES)
    if transport == "openai_tunnel":
        binaries += (release / "tunnel/tunnel-client",)
    for binary in binaries:
        require(binary.is_file() and os.access(binary, os.X_OK),
                "A required executable is missing or not executable.")
        resolved = binary.resolve(strict=True)
        safe_parents(resolved)
        info = resolved.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == 0 and not info.st_mode & 0o022,
                "A required executable has unsafe ownership or permissions.")
    entry = release / "mcp/dist/index.js"
    read_file(entry, 0)
    package = parse_json(read_file(release / "mcp/package.json", 0))
    require(package.get("version") == manifest["desktop_version"],
            "The installed Desktop Commander package version differs from the manifest.")
    require(runner([str(release / "node/bin/node"), "--version"], ctx, release)
            == "v" + manifest["node_version"], "The installed Node version differs from the manifest.")
    if transport == "openai_tunnel":
        version = runner([str(release / "tunnel/tunnel-client"), "--version"], ctx, release)
        require(re.search(r"(?<![0-9])v?" + re.escape(manifest["tunnel_version"]) + r"(?![0-9.])",
                          version), "The installed tunnel client version differs from the manifest.")
    runner([str(release / "node/bin/node"), "--check", str(entry)], ctx, release)
    runner([str(release / "node/bin/node"), str(release / "node/lib/node_modules/npm/bin/npm-cli.js"),
            "--version"], ctx, release)
    runner(["/usr/bin/rg", "--version"], ctx, release)
    runner([str(release / "node/bin/node"), "--input-type=module", "-e",
            "await import('sharp'); await import('esbuild'); "
            "await import('@modelcontextprotocol/sdk/server/index.js'); "
            "const r = await import('./dist/utils/ripgrep-resolver.js'); await r.getRipgrepPath();"],
           ctx, release, str(release / "mcp"))
    return release, manifest_bytes


def validate_runtime_context(ctx):
    require(os.geteuid() == ctx.uid, "Run preflight as the configured runtime user, not root.")
    require(os.environ.get("HOME") == str(ctx.home), "Runtime HOME does not match the configured account home.")
    require(ctx.workdir.is_dir() and os.access(ctx.workdir, os.R_OK | os.W_OK | os.X_OK),
            "The working directory is missing or not accessible to the runtime user.")


def validate_tunnel_inputs(ctx):
    validate_runtime_context(ctx)
    private_directory(ctx.config.parent, ctx.uid)
    private_directory(ctx.desktop_config.parent, ctx.uid)
    tunnel_bytes = read_file(ctx.config, ctx.uid, private=True, limit=65536)
    desktop_bytes = read_file(ctx.desktop_config, ctx.uid, private=True, limit=1_048_576)
    key_bytes = read_file(ctx.key, ctx.uid, private=True, limit=8192)
    port = validate_tunnel(parse_yaml(tunnel_bytes), ctx)
    validate_desktop(parse_json(desktop_bytes))
    validate_key(key_bytes)
    return port, tunnel_bytes, key_bytes


def validate_solaris_tunnel(ctx):
    """Check the account-owned current release and the active tunnel inputs."""
    port, _, _ = validate_tunnel_inputs(ctx)
    current = ctx.helpers / "current"
    require(current.is_symlink() and current.lstat().st_uid == ctx.uid,
            "Install the native OpenAI tunnel release before activating the service.")
    release = current.resolve(strict=True)
    require(release.parent == ctx.helpers / "releases",
            "The native selector must point to an installed local release.")
    manifest = parse_json(read_file(release / "release.json", ctx.uid, private=True))
    require(manifest.get("schema") == 1 and manifest.get("platform") == "solaris-amd64"
            and manifest.get("transport") == "openai_tunnel",
            "Activate the native release installed with dcmcp_transport=openai_tunnel.")
    for path in (ctx.helpers / "mcp-child", release / "bin/tunnel-client"):
        safe_parents(path)
        info = path.lstat()
        require(stat.S_ISREG(info.st_mode) and info.st_uid == ctx.uid
                and not info.st_mode & 0o022 and os.access(path, os.X_OK),
                "The native tunnel executable and MCP launcher must be owned and executable.")
    return port


def validate(ctx, release=None, check_port=False, runner=probe):
    port, tunnel_bytes, key_bytes = validate_tunnel_inputs(ctx)
    release, manifest_bytes = validate_release(ctx, release or ctx.current, runner)
    require(parse_json(manifest_bytes)["transport"] == "openai_tunnel",
            "OpenAI tunnel activation requires its explicit transport release.")
    helper_bytes = [read_file(ctx.helpers / name, 0)
                    for name in ("preflight.py", "readiness.py", "run", "mcp-child")]
    unit_bytes = read_file(ctx.unit, 0)
    require(all(os.access(ctx.helpers / name, os.X_OK) for name in ("run", "mcp-child")),
            "A managed launcher is not executable.")
    if check_port:
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
                listener.bind(("127.0.0.1", port))
        except OSError:
            raise InvalidConfig("The loopback health port is already in use or unavailable.") from None
    # Mutable Desktop Commander metadata/counters intentionally do not trigger restarts.
    digest = hashlib.sha256()
    for data in (str(release).encode(), tunnel_bytes, key_bytes, manifest_bytes, unit_bytes,
                 *helper_bytes):
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def validate_stdio(ctx, release, runner=probe):
    """Validate vendor-independent MCP installation without OpenAI credentials."""
    validate_runtime_context(ctx)
    private_directory(ctx.desktop_config.parent, ctx.uid)
    validate_desktop(parse_json(read_file(ctx.desktop_config, ctx.uid, private=True)))
    selected, manifest_bytes = validate_release(ctx, release, runner)
    require(parse_json(manifest_bytes)["transport"] == "stdio",
            "Stdio activation requires a vendor-independent release.")
    child = ctx.helpers / "mcp-child"
    read_file(child, 0)
    require(os.access(child, os.X_OK), "The vendor-independent MCP launcher is not executable.")
    return selected


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--user", required=True,
                        help="Explicit existing runtime account (no default)")
    parser.add_argument("--workdir")
    parser.add_argument("--home", help="Override passwd home only for isolated offline test fixtures")
    parser.add_argument("--account-home",
                        help="Override passwd home only for isolated offline test fixtures")
    parser.add_argument("--release")
    parser.add_argument("--stdio", action="store_true",
                        help="Validate standard MCP stdio without any tunnel configuration")
    parser.add_argument("--release-only", action="store_true",
                        help="Validate immutable artifacts without requiring active configuration")
    parser.add_argument("--fingerprint", action="store_true")
    parser.add_argument("--check-port", action="store_true")
    parser.add_argument("--solaris-tunnel", action="store_true",
                        help="Validate the installed Solaris tunnel and print its health port")
    args = parser.parse_args()
    try:
        account = pwd.getpwnam(args.user)
        home = absolute_path(args.home or account.pw_dir)
        helpers = home / ".local/share/desktop-commander-mcp" if args.solaris_tunnel else None
        ctx = Context(args.user, account.pw_uid, home,
                      absolute_path(args.workdir or account.pw_dir),
                      absolute_path(args.account_home or account.pw_dir), helpers=helpers)
        if args.solaris_tunnel:
            require(not any((args.release, args.release_only, args.stdio, args.fingerprint, args.check_port)),
                    "Solaris tunnel validation checks the current native release.")
            result = validate_solaris_tunnel(ctx)
        elif args.release_only:
            require(args.release and not args.fingerprint and not args.check_port
                    and not args.stdio,
                    "Release-only validation requires --release without activation options.")
            validate_runtime_context(ctx)
            validate_release(ctx, args.release)
            result = "Release validation passed (offline; no active configuration required)."
        elif args.stdio:
            require(args.release and not args.fingerprint and not args.check_port,
                    "Stdio preflight requires --release without tunnel activation options.")
            validate_stdio(ctx, args.release)
            result = "Stdio preflight passed (offline; no tunnel credentials required)."
        else:
            result = validate(ctx, args.release, args.check_port)
    except InvalidConfig as error:
        print("Preflight failed: " + str(error), file=sys.stderr)
        return 78
    except (OSError, KeyError, TypeError, ValueError, RecursionError):
        print("Preflight failed: required files, user or dependencies are unavailable/invalid.",
              file=sys.stderr)
        return 78
    print(result if args.fingerprint or args.release_only or args.stdio or args.solaris_tunnel
          else "Preflight passed (offline; no daemon or MCP started).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
