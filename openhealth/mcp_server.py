"""MCP server scaffold — live queries against the OpenHealth engine (stdio).

This exposes the OpenHealth derived layer to an agent (Claude Code / Codex /
any MCP client) as a small set of **live-query tools** over stdio:

- ``today`` / ``recovery`` — today's (or a given day's) recovery score, strain
  and sleep debt, assembled from indexed WHOOP records.
- ``journal_checkin`` — log a daily behavior check-in (boolean or scalar) into
  the index, feeding the correlations loop.
- ``correlations`` — current behavior→recovery impact prompts (graded, capped).
- ``ask`` — natural-language question answered from the local context files.

Status / SDK note
-----------------
The official MCP Python SDK (the ``mcp`` package, https://modelcontextprotocol.io)
is **not a stdlib module and is not currently vendored here** (core rule keeps
runtime deps at zero). So this file is a *scaffold*, deliberately split in two:

1. ``Engine`` + ``TOOLS`` — pure-stdlib, fully working tool implementations and
   their JSON Schemas. This half has no dependency on any SDK and is unit-test
   friendly. The real server and the fallback loop both call straight into it.
2. ``serve_stdio()`` — the transport. If the ``mcp`` SDK is importable it wires a
   real MCP stdio server (see the clearly marked ``TODO`` block, which mirrors
   the canonical SDK shape). If the SDK is absent, it runs a minimal,
   newline-delimited JSON-RPC-ish stdio loop so the engine is still drivable and
   testable today — and prints exactly how to enable the real server.

To enable the real MCP server, follow ``docs/mcp.md`` (add the optional ``mcp``
dependency, then this module lights up the SDK path automatically). Do **not**
treat the fallback loop as a spec-compliant MCP server; it is a stopgap.
"""

import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO

SERVER_NAME = "openhealth"
SERVER_VERSION = "0.1.0"


# ---------------------------------------------------------------------------
# Engine: pure-stdlib live-query logic. No MCP/SDK imports here on purpose.
# ---------------------------------------------------------------------------

class Engine:
    """Thin adapter from MCP tool calls to the OpenHealth engine.

    One instance is bound to a repository root. Every method returns a plain
    JSON-serializable dict, ready to become an MCP tool result. The engine only
    ever reads/writes through ``openhealth.index`` and the domain modules — it
    never touches raw source files.
    """

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._paths = None

    # -- lazy workspace wiring ------------------------------------------------
    def _ensure(self):
        from . import index
        from .storage import ensure_repo_structure

        if self._paths is None:
            self._paths = ensure_repo_structure(self.root)
            index.init_db(self._paths.db_path)
        return self._paths

    def _today(self) -> str:
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).date().isoformat()

    # -- tools ---------------------------------------------------------------
    def recovery(self, day: Optional[str] = None, baseline_window_days: int = 60) -> Dict[str, Any]:
        """Today's (or ``day``'s) recovery score / strain / sleep debt.

        Computes from indexed WHOOP records without persisting (a read-only live
        query). Returns ``available: False`` with a reason when HRV is missing,
        rather than raising — the agent can relay that cleanly.
        """
        from . import modules as modpkg

        modpkg.load_builtin()
        from .modules import recovery

        paths = self._ensure()
        day = day or self._today()
        payload = recovery.from_index(paths.db_path, day, baseline_window_days=baseline_window_days)
        if payload.get("hrv_ms") is None or payload.get("baseline_hrv_ms") is None:
            return {
                "available": False,
                "date": day,
                "reason": "no HRV / baseline in the index for this day",
            }
        result = modpkg.get_module("recovery").compute(payload)
        return {
            "available": True,
            "date": day,
            "metrics": result.metrics,
            "notes": result.notes,
        }

    def journal_checkin(
        self,
        behavior_id: str,
        value: Any,
        day: Optional[str] = None,
        category: Optional[str] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Persist a daily behavior check-in into the index (feeds correlations).

        ``value`` is typically a boolean (did the behavior happen) but a scalar
        is accepted too. The record is upserted with a deterministic id so the
        same behavior on the same day overwrites rather than duplicates.
        """
        from . import index

        paths = self._ensure()
        day = day or self._today()
        record = {
            "id": "obs-journal-%s-%s" % (day, behavior_id),
            "record_type": "Observation",
            "source_id": "journal",
            "title": "Journal check-in: %s" % behavior_id,
            "summary": (note or "Logged %s = %r on %s." % (behavior_id, value, day)),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.9,
            "date": day,
            "tags": ["journal", "checkin"],
            "metadata": {"behavior_id": behavior_id, "category": category or "unknown"},
            "observation_kind": "journal_entry",
            "metric_name": behavior_id,
            "value": value,
        }
        index.upsert_record(paths.db_path, record)
        return {"saved": True, "record_id": record["id"], "date": day, "behavior_id": behavior_id}

    def correlations(self, window_days: int = 90, as_of: Optional[str] = None) -> Dict[str, Any]:
        """Current behavior→recovery impact prompts (graded, capped, read-only)."""
        from . import modules as modpkg

        modpkg.load_builtin()
        from .modules import correlations

        paths = self._ensure()
        behaviors = correlations.from_index(paths.db_path, window_days=window_days, as_of=as_of)
        result = modpkg.get_module("correlations").compute(
            {"behaviors": behaviors, "window_days": window_days}
        )
        return {
            "window_days": window_days,
            "behaviors_considered": len(behaviors),
            "insights": result.insights,
            "notes": result.notes,
        }

    def ask(self, question: str, max_tokens: int = 900) -> Dict[str, Any]:
        """Answer a natural-language question from local context files.

        Reuses ``openhealth.ask``: with an Anthropic key set it returns a cited
        answer; without one it returns the offline prompt bundle the agent can
        answer itself. Output is captured to a string (no terminal streaming).
        """
        import io

        from . import ask as ask_mod

        self._ensure()
        buffer = io.StringIO()
        err = io.StringIO()
        code = ask_mod.run_ask(
            self.root, question, stream=False, out=buffer, err=err, max_tokens=max_tokens
        )
        return {
            "ok": code == 0,
            "answer": buffer.getvalue().strip(),
            "error": err.getvalue().strip() or None,
        }


# ---------------------------------------------------------------------------
# Tool registry: declarative schemas + dispatch into the Engine.
# ---------------------------------------------------------------------------

def _tool_specs() -> List[Dict[str, Any]]:
    """MCP-style tool declarations (name, description, JSON Schema input)."""
    return [
        {
            "name": "today",
            "description": "Today's recovery score, strain and sleep debt from indexed WHOOP data.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "baseline_window_days": {"type": "integer", "default": 60},
                },
            },
            "handler": lambda engine, args: engine.recovery(
                day=None, baseline_window_days=int(args.get("baseline_window_days", 60))
            ),
        },
        {
            "name": "recovery",
            "description": "Recovery score / strain / sleep debt for a given day (default today).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "day": {"type": "string", "description": "ISO date YYYY-MM-DD."},
                    "baseline_window_days": {"type": "integer", "default": 60},
                },
            },
            "handler": lambda engine, args: engine.recovery(
                day=args.get("day"), baseline_window_days=int(args.get("baseline_window_days", 60))
            ),
        },
        {
            "name": "journal_checkin",
            "description": "Log a daily behavior check-in (boolean/scalar) into the index.",
            "inputSchema": {
                "type": "object",
                "required": ["behavior_id", "value"],
                "properties": {
                    "behavior_id": {"type": "string"},
                    "value": {"description": "Usually a boolean; scalar accepted."},
                    "day": {"type": "string", "description": "ISO date YYYY-MM-DD (default today)."},
                    "category": {"type": "string"},
                    "note": {"type": "string"},
                },
            },
            "handler": lambda engine, args: engine.journal_checkin(
                behavior_id=args["behavior_id"],
                value=args["value"],
                day=args.get("day"),
                category=args.get("category"),
                note=args.get("note"),
            ),
        },
        {
            "name": "correlations",
            "description": "Current behavior→recovery impact prompts (graded and capped).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "window_days": {"type": "integer", "default": 90},
                    "as_of": {"type": "string", "description": "ISO date to evaluate as of (default today)."},
                },
            },
            "handler": lambda engine, args: engine.correlations(
                window_days=int(args.get("window_days", 90)), as_of=args.get("as_of")
            ),
        },
        {
            "name": "ask",
            "description": "Answer a natural-language question from local context files.",
            "inputSchema": {
                "type": "object",
                "required": ["question"],
                "properties": {
                    "question": {"type": "string"},
                    "max_tokens": {"type": "integer", "default": 900},
                },
            },
            "handler": lambda engine, args: engine.ask(
                question=args["question"], max_tokens=int(args.get("max_tokens", 900))
            ),
        },
    ]


def list_tools() -> List[Dict[str, Any]]:
    """Public tool catalog (no handlers), suitable for an MCP ``list_tools``."""
    return [{k: spec[k] for k in ("name", "description", "inputSchema")} for spec in _tool_specs()]


def _dispatch_table(engine: Engine) -> Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]]:
    return {spec["name"]: (lambda args, _h=spec["handler"]: _h(engine, args)) for spec in _tool_specs()}


def call_tool(engine: Engine, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Invoke a tool by name. Raises ``KeyError`` for an unknown tool."""
    table = _dispatch_table(engine)
    if name not in table:
        raise KeyError("unknown tool %r; known: %s" % (name, ", ".join(sorted(table))))
    return table[name](arguments or {})


# ---------------------------------------------------------------------------
# Transport.
# ---------------------------------------------------------------------------

def _sdk_available() -> bool:
    import importlib.util

    return importlib.util.find_spec("mcp") is not None


def serve_stdio(root: Path, *, out: Optional[TextIO] = None, in_: Optional[TextIO] = None) -> int:
    """Serve the engine over stdio.

    Uses the real MCP SDK when present; otherwise runs the stdlib fallback loop
    and tells the operator how to enable the real server.
    """
    engine = Engine(root)
    if _sdk_available():
        return _serve_with_sdk(engine)
    return _serve_fallback(engine, out=out or sys.stdout, in_=in_ or sys.stdin)


def _serve_with_sdk(engine: Engine) -> int:
    """Wire the official MCP SDK stdio server.

    TODO(mcp-sdk): This is intentionally a documented stub, not live code, until
    the optional ``mcp`` dependency is added (see docs/mcp.md). When enabled, the
    canonical shape is roughly:

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

    The exact symbols above must be validated against the installed SDK version
    before this stub is promoted to real code; do not assume this signature is
    correct without checking the SDK that gets pinned in pyproject.
    """
    sys.stderr.write(
        "openhealth.mcp_server: the 'mcp' SDK is importable but the SDK transport "
        "is still a documented stub. See docs/mcp.md to finish wiring it, or run "
        "with the SDK absent to use the stdlib fallback loop.\n"
    )
    return 2


def _serve_fallback(engine: Engine, *, out: TextIO, in_: TextIO) -> int:
    """Minimal newline-delimited JSON stdio loop (NOT spec-compliant MCP).

    Protocol (one JSON object per line, one JSON response per line):
      {"method": "list_tools"}                                  -> {"tools": [...]}
      {"method": "call_tool", "name": "...", "arguments": {...}} -> {"result": {...}}
      {"method": "ping"}                                         -> {"result": "pong"}

    A stopgap so the engine is drivable and testable before the SDK is wired.
    """
    sys.stderr.write(
        "openhealth.mcp_server: 'mcp' SDK not installed — running the stdlib "
        "fallback stdio loop (newline-delimited JSON). This is NOT a spec-compliant "
        "MCP server; see docs/mcp.md to enable the real one.\n"
    )
    sys.stderr.flush()

    for raw in in_:
        line = raw.strip()
        if not line:
            continue
        response = _handle_fallback_line(engine, line)
        out.write(json.dumps(response, ensure_ascii=False) + "\n")
        out.flush()
        if response.get("_stop"):
            break
    return 0


def _handle_fallback_line(engine: Engine, line: str) -> Dict[str, Any]:
    """Parse + dispatch one fallback-protocol request line into a response dict."""
    try:
        request = json.loads(line)
    except ValueError as exc:
        return {"error": "invalid JSON: %s" % exc}

    method = request.get("method")
    try:
        if method == "ping":
            return {"result": "pong"}
        if method in ("shutdown", "exit"):
            return {"result": "bye", "_stop": True}
        if method == "list_tools":
            return {"tools": list_tools()}
        if method == "call_tool":
            name = request.get("name")
            if not name:
                return {"error": "call_tool requires a 'name'"}
            result = call_tool(engine, name, request.get("arguments") or {})
            return {"result": result}
        return {"error": "unknown method %r" % method}
    except KeyError as exc:
        return {"error": str(exc)}
    except Exception as exc:  # surface engine errors as a clean response, don't crash the loop
        return {"error": "%s: %s" % (type(exc).__name__, exc)}


# ---------------------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """``python3 -m openhealth.mcp_server [--repo-root .] [--list-tools]``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="openhealth.mcp_server",
        description="MCP server scaffold (stdio) for live OpenHealth queries.",
    )
    parser.add_argument("--repo-root", default=".", help="Path to the OpenHealth repository root.")
    parser.add_argument(
        "--list-tools",
        action="store_true",
        help="Print the tool catalog as JSON and exit (no server).",
    )
    args = parser.parse_args(argv)

    if args.list_tools:
        print(json.dumps({"server": SERVER_NAME, "version": SERVER_VERSION, "tools": list_tools()},
                         indent=2, ensure_ascii=False))
        return 0

    return serve_stdio(Path(args.repo_root).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
