# AI client configuration examples

Configure a **stdio** MCP server using the launcher described in the
[main installation guide](../README.md#2-install-configure-and-activate-standard-mcp).
These illustrative configurations assume an existing authenticated SSH
connection to a Linux target. For local clients, use the appropriate direct
`mcp-child` command; for Solaris, see the [native guide](solaris-portability.md).
Review the [security boundaries](security.md). These are non-exhaustive
examples, not a claim of end-to-end validation for every client.

**Gemini CLI** (`mcpServers` inside its `settings.json`):

```json
{
  "mcpServers": {
    "desktop-commander": {
      "command": "ssh",
      "args": ["-T", "-o", "BatchMode=yes", "USER@YOUR_HOST", "/usr/local/libexec/desktop-commander-mcp/USER/mcp-child"]
    }
  }
}
```

**Codex CLI** (`config.toml`):

```toml
[mcp_servers.desktop-commander]
command = "ssh"
args = ["-T", "-o", "BatchMode=yes", "USER@YOUR_HOST", "/usr/local/libexec/desktop-commander-mcp/USER/mcp-child"]
```

**Claude Code**: register a stdio MCP server using its MCP CLI/settings and
the same SSH command and arguments. Do not assume that every AI product
supports remote private SSH or the same client-side configuration format.

Official references: [Gemini CLI](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md),
[Claude Code](https://code.claude.com/docs/en/mcp),
[Codex CLI](https://developers.openai.com/codex/mcp).

## Optional cloud connectivity

For a supported hosted client that cannot launch a local or SSH subprocess,
see the [implemented cloud adapter](openai-tunnel.md). Other cloud providers
require their own compatible, implemented and validated adapters.
