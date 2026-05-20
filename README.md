# MCP Proxy

A minimal generic MCP tool-filtering proxy. It connects to an upstream MCP server and exposes only the tools allowed by an allowlist or denylist in a per-server configuration file.

## Use cases

Use this proxy when an MCP server exposes multiple tools but you only want an agent to see and call a subset of them.

Examples:

- Expose only `google_search` from a Serper MCP server
- Hide dangerous or irrelevant tools from a GitHub MCP server
- Reuse the same `mcp_proxy.py` for multiple upstream MCP servers by providing different `.env` files

## File structure

```text
mcp-proxy/
├── mcp_proxy.py        # Generic MCP proxy script
├── serper.env          # Example Serper MCP config
├── github.env          # Example GitHub MCP config
└── tavily.env          # Example Tavily MCP config
```

In practice, keep a single `mcp_proxy.py` and create one separate `.env` file for each upstream MCP server.

## Requirements

Install `uv` first.

`mcp_proxy.py` uses PEP 723 script metadata, so running it with `uv run` installs the required Python dependencies automatically.

## Configuration file

Each upstream MCP server uses its own `.env` file, for example `serper.env`:

```env
# Upstream MCP server config
UPSTREAM_TYPE=http
UPSTREAM_URL=https://mcp.example.com/mcp
UPSTREAM_HEADER_Authorization=Bearer <your-token>

# Allowlist: expose only these tools
ALLOW_TOOLS=google_search

# Denylist: hide these tools
# DENY_TOOLS=google_search_images,google_search_videos,webpage_scrape
```

For SSE upstream servers, use the same URL/header options with `UPSTREAM_TYPE=sse`:

```env
UPSTREAM_TYPE=sse
UPSTREAM_URL=https://mcp.example.com/sse
UPSTREAM_HEADER_Authorization=Bearer <your-token>
ALLOW_TOOLS=google_search
```

For stdio upstream servers, provide the command, optional arguments, and optional environment variables:

```env
UPSTREAM_TYPE=stdio
UPSTREAM_COMMAND=npx
UPSTREAM_ARGS=-y @example/mcp-server
UPSTREAM_ENV_API_KEY=<your-token>
ALLOW_TOOLS=google_search
```

A stdio upstream must not point back to this proxy script, because that would recursively start more proxy processes.

### Config options

| Option | Required | Description |
| --- | --- | --- |
| `UPSTREAM_TYPE` | No | Upstream transport: `http`, `sse`, or `stdio`. Defaults to `http` |
| `UPSTREAM_URL` | For `http` / `sse` | Upstream MCP server URL |
| `UPSTREAM_HEADER_*` | No | HTTP headers forwarded to `http` and `sse` upstream MCP servers |
| `UPSTREAM_COMMAND` | For `stdio` | Command used to start the upstream stdio MCP server |
| `UPSTREAM_ARGS` | No | Arguments for `UPSTREAM_COMMAND`, split using shell-like quoting rules |
| `UPSTREAM_ENV_*` | No | Environment variables passed to the upstream stdio MCP server |
| `ALLOW_TOOLS` | No | Comma-separated tool allowlist |
| `DENY_TOOLS` | No | Comma-separated tool denylist |

### Allowlist and denylist behavior

- If `ALLOW_TOOLS` is set, only those tools are exposed
- If `ALLOW_TOOLS` is not set, tools listed in `DENY_TOOLS` are hidden
- If neither option is set, all upstream tools are exposed
- If both are set, `ALLOW_TOOLS` takes precedence

## Agent / Claude Code configuration example

```json
{
  "mcpServers": {
    "serper": {
      "command": "uv",
      "args": ["run", "<absolute-path-to>/mcp_proxy.py"],
      "env": {
        "ENV_FILE": "<absolute-path-to>/serper.env"
      }
    },
    "github": {
      "command": "uv",
      "args": ["run", "<absolute-path-to>/mcp_proxy.py"],
      "env": {
        "ENV_FILE": "<absolute-path-to>/github.env"
      }
    }
  }
}
```

On Windows, forward slashes can be used to avoid JSON backslash escaping issues:

```json
{
  "mcpServers": {
    "serper": {
      "command": "uv",
      "args": ["run", "C:/path/to/mcp-proxy/mcp_proxy.py"],
      "env": {
        "ENV_FILE": "C:/path/to/mcp-proxy/serper.env"
      }
    }
  }
}
```

## How it works

The proxy communicates with the agent over stdio and connects to the upstream MCP server over HTTP, SSE, or stdio:

1. The agent requests the tool list
2. The proxy fetches the full tool list from the upstream MCP server
3. The proxy filters tools using `ALLOW_TOOLS` / `DENY_TOOLS`
4. The agent only sees the filtered tool list
5. When the agent calls a tool, the proxy checks whether the tool is allowed
6. Allowed calls are forwarded to the upstream MCP server

## Local checks

Run a syntax check with:

```bash
uv run python -m py_compile mcp_proxy.py
```

If you run the proxy directly without setting `ENV_FILE`, it will fail with:

```text
RuntimeError: ENV_FILE is required
```

This is expected. In normal use, `ENV_FILE` is passed by the agent MCP configuration.

## Security notes

- Do not commit real tokens, API keys, or private upstream URLs to a public repository
- Create `.env` files locally for each environment and keep them ignored by Git
- `Bearer <your-token>`, `<absolute-path-to>`, and `C:/path/to/...` are placeholders
- If a token has appeared in logs, chat history, or Git history, rotate it immediately

## Current limitations

- Supported upstream transports are `http`, `sse`, and `stdio`
- A new upstream session is created for each tool-list or tool-call request; this keeps the implementation simple but is not optimized for high throughput

## Example: expose only Serper search

`serper.env`:

```env
UPSTREAM_TYPE=http
UPSTREAM_URL=https://mcp.example.com/mcp
UPSTREAM_HEADER_Authorization=Bearer <your-token>
ALLOW_TOOLS=google_search
```

Agent configuration:

```json
{
  "mcpServers": {
    "serper": {
      "command": "uv",
      "args": ["run", "<absolute-path-to>/mcp_proxy.py"],
      "env": {
        "ENV_FILE": "<absolute-path-to>/serper.env"
      }
    }
  }
}
```

With this configuration, the agent can only see and call `google_search`. Other upstream tools are not exposed to the agent.
