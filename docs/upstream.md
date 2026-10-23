# Upstream inspection and implementation decisions

Initial inspection through the GitHub connector on 2026-10-10. The target
repository was private, used main and contained only README.md. The
recursive tree contained no AGENTS.md
or other instructions. The ruleset query returned 403 because the feature was
unavailable on the private repository's plan; the branch was reported as
unprotected. This does not replace user authorization to update refs/open PRs.

## RPM distribution reconnaissance (2026-10-23)

RHEL 10 uses DNF and provides `python3-pyyaml`, `libatomic`, `gcc`, `make`
through its RPM packaging ecosystem. Fedora 43/44 uses DNF5 and packages
`ripgrep`, `python3-pyyaml` and `libatomic` natively.

- RHEL documentation: <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html-single/managing_software_with_the_dnf_tool/index>
- RHEL 10 package manifest: <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html-single/package_manifest/index>
- Fedora ripgrep builds (Fedora/EPEL 10): <https://packages.fedoraproject.org/pkgs/rust-ripgrep/ripgrep/>
- RHEL Extensions and EPEL note: <https://access.redhat.com/solutions/3358>
- Ansible dnf4/dnf5 backends: <https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/dnf_module.html> and <https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/dnf5_module.html>
- RHEL SELinux guidance: <https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/10/html-single/using_selinux/index>

The installation deliberately leaves subscription/repository enrollment and
SELinux policy management to the administrator. `restorecon` uses distro
file contexts for *managed* paths only. Launching a system-labeled
`/usr/bin/python3` instead of directly executing an ad hoc script is an
additional conservative measure for SELinux. It does not prove all AVCs are
absent or the service works under Enforcing mode. These decisions need real
host confirmation. Fedora 45 was still a beta/prerelease at review and is
not in the supported host allowlist.

## Release refresh on 2026-10-22

Desktop Commander [v0.3.1](https://github.com/wonderwhy-er/DesktopCommanderMCP/releases/tag/v0.3.1)
was published on 2026-10-22, following v0.3.0 on 2026-10-13. The release has
`package-lock.json` Git blob `b1c6da69633e597dab119e1173935523a4d4caa8`.
The tag's package.json is 0.3.1, but the lockfile's root version remains 0.3.0;
its dependency maps are equal to package.json. The upstream changelog fixes
PDF file handle closing, streamed file reads, preview security policy and an
`unpdf` dependency regression. The earlier 0.3.0 improved path validation,
process cleanup and search behavior.

The new pinned lockfile has **one** local `file:vendor/telemetry-contract`
dependency, represented by a linked `node_modules/@desktop-commander/telemetry-contract`
entry and vendored metadata. These entries intentionally have no npm integrity
hashes. The release verifier explicitly checks the name, path, version, link,
and tracked non-symlink source files against the immutable Git checkout. It
continues to require SHA integrity and official npm HTTPS URLs for every other
package. Arbitrary local dependencies are not allowed. Dependency lifecycle
scripts remain disabled during `npm ci`.

A native SDK tool-name comparison of v0.2.52 and v0.3.1 identified one
intentional upstream surface change: `get_prompts` is absent in v0.3.1. The
other 25 MCP tool names are unchanged, including terminal commands, files and
PDF operations. Our headless launch already disables onboarding.

The Node.js 24.21.0 and OpenAI tunnel-client 0.0.16 pins are unchanged.
This section supersedes the 2026-10-10 Desktop Commander version investigation
below, which is retained as historical background only.

## Desktop Commander

Latest release inspected: [v0.2.52](https://github.com/wonderwhy-er/DesktopCommanderMCP/releases/tag/v0.2.52).

| Decision | Evidence |
| --- | --- |
| Invoke dist/index.js with --no-onboarding | [src/index.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/index.ts) and [package.json](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/package.json) |
| Use an explicit process HOME; configuration lives outside the working directory | [src/config.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/config.ts) |
| Strict JSON, writable by the process user | [config-manager.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/config-manager.ts) |
| Keep MCP pipes/stdout connected to the supervisor instead of using a standalone stdio service | [custom-stdio.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/custom-stdio.ts) |
| Use system ripgrep when postinstall is disabled | [ripgrep-resolver.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/utils/ripgrep-resolver.ts) |
| Immutable source, npm ci and dependency integrity | [package-lock.json](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/package-lock.json), Git blob 5aa49fbc9b44e6506d79b1481d608ff819fd7fc7 |
| Browser/PDF is outside the versioned installation | [pdf/markdown.ts](https://github.com/wonderwhy-er/DesktopCommanderMCP/blob/v0.2.52/src/tools/pdf/markdown.ts) |

On the observed main branch, package.json also reported 0.2.52, but required
Node >=22.12.0 and had different dependencies. Tag 0.2.52 specifies Node >=18.0.0.
The version number alone does not identify that source. This implementation
uses the tag's commit and Node 24, which meets both declared minimum versions;
it does not mix main source with the release tag.

The tag's lockfile has stale root version metadata (0.2.39), but its three
dependency maps match package.json 0.2.52. Its 1,142 packages have official
registry HTTPS resolved URLs and sha512 integrity values. The role verifies
those maps/hashes without modifying the lockfile; npm ci must fail on any
installation inconsistency. The initial conclusion came from content inspection;
subsequent npm installation/build results are recorded in [validation.md](validation.md).

The release's MCPB was inspected as an alternative. Its build installs/bundles
dependencies in the publishing environment; the final distribution of native
modules per architecture was not verified by the connector, which cannot
download binaries. Ansible therefore builds the pinned source on the target
to obtain architecture-specific native modules with the lockfile's hashes.

The native daemon runs as the existing mcp_operator account with
HOME=/var/lib/desktop-commander-mcp/home. Its working directory defaults to the
account's passwd home. The dedicated process home prevents config/cache
collisions with Remote Desktop Commander or interactive MCP clients using
the same UID; it adds no users or sudoers restrictions. This follows
os.homedir() in the inspected Node source. Native tests verify that the
daemon and fixture use their explicit HOME.

## OpenAI tunnel-client

Default branch: master. Latest release inspected:
[v0.0.16](https://github.com/openai/tunnel-client/releases/tag/v0.0.16),
published on 2026-10-06. The release was inspected by tag.

| Decision | Evidence |
| --- | --- |
| Use a runtime key and document access/registration separately | [README](https://github.com/openai/tunnel-client/blob/v0.0.16/README.md), [onboarding](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/onboarding.md), [permissions](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/permissions.md) |
| One service supervises a stdio child | [stdio_command.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/mcpclient/stdio_command.go), [stdio_command_factory.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/mcpclient/stdio_command_factory.go) |
| Shut down when the child exits/a pipe closes; forward signals and lifecycle hooks | [stdio_command.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/mcpclient/stdio_command.go) |
| Never overlap stdio daemons for the same tunnel ID | [configuration: stdio deployment limits](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/configuration.md#stdio-deployment-limits) |
| Outbound HTTPS and a private MCP server | [architecture](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/architecture.md) |
| Native YAML, config_version 2 and file: references for runtime keys | [configuration](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/configuration.md), [file_config.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/file_config.go), [config.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimeconfig/config.go) |
| Foreground systemd process with restart | [systemd-vm](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/deployment/systemd-vm.md) |
| Local readiness is separate from stdio discovery | [health documentation](https://github.com/openai/tunnel-client/blob/v0.0.16/docs/health.md), [health.go](https://github.com/openai/tunnel-client/blob/v0.0.16/pkg/runtimehealth/health.go) |
| doctor inspects stdio without starting a subprocess | [doctor_command.go](https://github.com/openai/tunnel-client/blob/v0.0.16/cmd/client/doctor_command.go), [stdio_preflight.go](https://github.com/openai/tunnel-client/blob/v0.0.16/cmd/client/stdio_preflight.go) |
| ZIP files contain files at the archive root | [package_release_archive.sh](https://github.com/openai/tunnel-client/blob/v0.0.16/scripts/package_release_archive.sh) |

The official full-client ZIPs were selected to retain doctor, without using
runtimes connect as a second supervisor or enabling Cloudflared.
The SHA-256 values below come from the release asset digests in the
[official release API](https://api.github.com/repos/openai/tunnel-client/releases/tags/v0.0.16):

| Artifact | SHA-256 |
| --- | --- |
| tunnel-client-v0.0.16-linux-amd64.zip | d60cdba019bce451bcc3a15478cc5b9cb11270b049f5b56ea39a80b517f8b117 |
| tunnel-client-v0.0.16-linux-arm64.zip | 963d0384aaa7c798778479c45673f9051a4039dd891aef8f8978d2a1a628b74f |

get_url validates SHA-256 before extraction. This checks integrity against the
reviewed pins; it does not claim provenance/Sigstore verification. Upstream
also provides SHA256SUMS.txt and a provenance bundle, and its README documents
gh attestation verify for operators who require that verification.

Upstream references the [official public guide](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels).
Its contents were not accessible during the initial inspection: the permitted
connector could read only supported GitHub endpoints. The implementation uses
the GitHub sources actually read, without attributing unverified content to
the external guide.

## Node and controller

Node 24.21.0 was confirmed in the
[Node releases](https://github.com/nodejs/node/releases/tag/v24.21.0).
Hashes were read from the official website's release post for Node 24.21.0.

| Artifact | SHA-256 |
| --- | --- |
| node-v24.21.0-linux-x64.tar.xz | fd8e59d5a511510f6a298afb548f18c7d2b1be404d8b4a27d94fbe49f56cb2d6 |
| node-v24.21.0-linux-arm64.tar.xz | 6ad1325edbdb5649c379b75a237147a666c95d4f9ae8d340fef2d1575d289ad2 |

Downloads use the nodejs.org URLs published in that post, with pinned digest
verification during installation. No binary downloads ran during the initial
GitHub-only inspection; later installation test results are recorded in
[validation.md](validation.md).

ansible-core [2.21.5](https://github.com/ansible/ansible/releases/tag/v2.21.5)
was the latest stable version inspected. Its
[pyproject](https://github.com/ansible/ansible/blob/v2.21.5/pyproject.toml)
requires Python >=3.12 and lists 3.12, 3.13 and 3.14.
ansible-lint [26.9.0](https://github.com/ansible/ansible-lint/releases/tag/v26.9.0)
was the latest release inspected.

This document records sources and implementation inferences. It does not claim
production installation, account eligibility, successful local validation or a host connection.
Executed test results are recorded separately in [validation.md](validation.md).
