# MCP server (scaffold)

`openhealth.mcp_server` exposes the OpenHealth derived layer to an MCP client
(Claude Code, Codex, any MCP host) as a small set of **live-query tools** over
stdio.

## Status

This is a **scaffold**, split into two clean halves:

- **Engine + tool registry** (`Engine`, `list_tools()`, `call_tool()`) — pure
  stdlib, fully working, unit-test friendly. No SDK dependency.
- **Transport** (`serve_stdio()`) — uses the official MCP SDK when it is
  installed; otherwise runs a minimal stdlib fallback loop so the engine is
  still drivable today.

The official MCP Python SDK (the `mcp` package) is **not** part of the standard
library and is intentionally **not** a hard dependency (OpenHealth's core rule
keeps runtime deps at zero). Until you add it, the real SDK transport is a
documented stub — see "Enable the real server" below.

## Tools

| Tool | What it does |
|------|--------------|
| `today` | Today's recovery score, strain and sleep debt from indexed WHOOP data. |
| `recovery` | Same, for a given `day` (ISO date). |
| `journal_checkin` | Log a daily behavior check-in (boolean/scalar) into the index — feeds the correlations loop. |
| `correlations` | Current behavior→recovery impact prompts (graded and capped by the evidence scale). |
| `ask` | Answer a natural-language question from the local context files. |

Inspect the catalog (no server needed):

```bash
python3 -m openhealth.mcp_server --list-tools
```

## Run it now (stdlib fallback)

With the SDK absent, the server runs a **newline-delimited JSON** loop on stdio.
This is a stopgap, **not** a spec-compliant MCP server, but it lets you exercise
every tool end to end:

```bash
python3 -m openhealth.mcp_server --repo-root /path/to/openhealth
```

Then write one JSON object per line to stdin; read one JSON object per line back:

```json
{"method": "list_tools"}
{"method": "call_tool", "name": "today", "arguments": {}}
{"method": "call_tool", "name": "journal_checkin", "arguments": {"behavior_id": "lifestyle.alcohol", "value": true}}
{"method": "call_tool", "name": "correlations", "arguments": {"window_days": 90}}
{"method": "ping"}
{"method": "shutdown"}
```

Errors (unknown tool, bad JSON, engine exceptions) come back as
`{"error": "..."}` and never crash the loop.

## Enable the real server

1. **Add the optional dependency.** This repo's `pyproject.toml` is owned
   centrally — do not edit it as part of an unrelated change. Ask the maintainer
   to add an optional-extra so the SDK stays out of the zero-dep core:

   ```toml
   # [project.optional-dependencies]
   mcp = [
       "mcp>=1.2",
   ]
   ```

   Install with:

   ```bash
   pip install -e ".[mcp]"
   # or, ad hoc:  pip install "mcp>=1.2"
   ```

2. **Finish the transport.** `serve_stdio()` already detects the SDK
   (`importlib.util.find_spec("mcp")`) and routes to `_serve_with_sdk()`. That
   function currently contains a documented stub. Promote it to live code using
   the canonical SDK shape (validate the exact symbols against the version you
   pinned — the SDK API has moved between releases):

   ```python
   import anyio
   from mcp.server import Server
   from mcp.server.stdio import stdio_server
   import mcp.types as types

   server = Server(SERVER_NAME)

   @server.list_tools()
   async def _list() -> list[types.Tool]:
       return [types.Tool(**t) for t in list_tools()]

   @server.call_tool()
   async def _call(name: str, arguments: dict) -> list[types.TextContent]:
       result = call_tool(engine, name, arguments)
       return [types.TextContent(type="text", text=json.dumps(result, ensure_ascii=False))]

   async def _run():
       async with stdio_server() as (read, write):
           await server.run(read, write, server.create_initialization_options())

   anyio.run(_run)
   return 0
   ```

   The engine layer does **not** change — `call_tool(engine, name, arguments)`
   returns the same JSON-serializable dicts the fallback loop already uses.

## Register with an MCP client

Once the real transport is live, point your MCP host at the stdio command. For a
Claude Code / generic `mcpServers` config:

```json
{
  "mcpServers": {
    "openhealth": {
      "command": "python3",
      "args": ["-m", "openhealth.mcp_server", "--repo-root", "/path/to/openhealth"]
    }
  }
}
```

## Design notes

- The engine reads and writes **only** through `openhealth.index` and the domain
  modules — never the raw source files.
- `recovery` / `today` are read-only live queries; they do not persist. They
  return `{"available": false, "reason": ...}` when HRV is missing for the day,
  so the agent can relay that cleanly instead of erroring.
- `correlations` stays graded and capped by `openhealth.evidence`; nothing here
  diagnoses or prescribes. Outputs are prompts for review.
