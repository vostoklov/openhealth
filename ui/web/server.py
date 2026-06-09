#!/usr/bin/env python3
"""OpenHealth dashboard bridge — static server + local AI agent runner.

The "agency" front of the dashboard: serves the dashboard statics, exposes the
local data file and can run a local AI agent CLI (Claude Code / Codex) over the
user's local data, returning the result to the page.

stdlib only (repo rule): argparse, http.server, json, subprocess, shutil, pathlib.

Endpoints:
    GET  /            -> static files from --dir (index.html by default)
    GET  /api/data    -> data.local.json from --dir (200), or {"demo": true}
    GET  /api/health  -> {"ok": true, "agents": {"claude": bool, "codex": bool,
                          "openhealth": bool}}
    POST /api/agent   -> run a local agent CLI for a whitelisted task.
                         body: {"task": "insight" | "correlations" | "research"
                                        | "transcript",
                                "param": "optional topic, e.g. 'HRV'",
                                "lang": "ru" | "en"}
                         reply (always 200 for a valid request; the outcome is
                         in "status"):
                           {"status": "ok", "agent": "claude", "task": "...",
                            "result": "<text>", "took_ms": N}
                           {"status": "timeout", ...}
                           {"status": "error", "message": "...", ...}
                           {"status": "no_agent", "message": "..."}
                         Request-level problems use HTTP 4xx with
                         {"status": "error", "message": "..."}.

Security model:
    - binds to 127.0.0.1 only;
    - task names come from a fixed whitelist; param is a plain string,
      whitespace-collapsed and capped at 200 chars;
    - the prompt is passed to the CLI as a single argv element, never through
      a shell (no shell=True anywhere);
    - POST must be application/json with body <= 64 KB;
    - same-origin usage only, no CORS headers on purpose.

PRIVACY: data.local.json holds real personal health data and lives in the
runtime directory (--dir), never in the repo. This file contains no data.

Usage:
    python3 server.py [--port 8770] [--dir .]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
DEFAULT_PORT = 8770
DATA_FILE = "data.local.json"

MAX_BODY_BYTES = 64 * 1024
MAX_PARAM_LEN = 200
MAX_SUMMARY_CHARS = 1500
MAX_STDERR_TAIL = 500
AGENT_TIMEOUT_S = 120

ALLOWED_TASKS = frozenset({"insight", "correlations", "research", "transcript"})
AGENT_BINARIES = ("claude", "codex", "openhealth")

# --- prompts (Russian, short, with the repo safety rules baked in) ---------

PROMPT_INTRO = "Ты — агент OpenHealth, локальный ассистент по личным данным здоровья."

PROMPT_SAFETY = (
    "Правила безопасности: ты не врач, не ставь диагнозов и не назначай лечение. "
    "Каждому выводу давай уровень доверия C1-C5 (C1 — слабая догадка, C5 — твёрдое "
    "доказательство); вывод уровня C3 и ниже формулируй как вопрос-гипотезу. "
    "Личный паттерн из корреляций — максимум C2 без n-of-1 проверки. "
    "Red flags (боль в груди, обморок, мысли о причинении себе вреда, критические "
    "значения) — не интерпретируй, сразу советуй обратиться к врачу."
)

TASK_INSTRUCTIONS = {
    "insight": (
        "Задача: проанализируй мои данные recovery/HRV/сон за период из блока ДАННЫЕ. "
        "Дай 2-3 наблюдения и 1-3 конкретных действия на сегодня, каждое с уровнем "
        "доверия C1-C5."
    ),
    "correlations": (
        "Задача: по данным журнала и recovery из блока ДАННЫЕ найди вероятные связи "
        "поведение -> recovery относительно личного baseline. Помечай каждую уровнем "
        "C1-C5; личный паттерн — максимум C2, формулируй как гипотезу для n-of-1 "
        "проверки. Назови, какие другие факторы могли бы объяснить тот же паттерн."
    ),
    "research": (
        "Задача: сделай краткий обзор доказательной базы по теме «{topic}» "
        "применительно к recovery/HRV/сну: 3-5 пунктов, каждый с C-grade (качество "
        "доказательств) и одной строкой сути."
    ),
}

TRANSCRIPT_STUB = {
    "status": "ok",
    "agent": "none",
    "task": "transcript",
    "stub": True,
    "result": (
        "Модуль транскриптов не подключён. Это честная заглушка: когда появится "
        "локальный архив транскриптов встреч и консультаций, bridge начнёт отдавать "
        "их анализ здесь."
    ),
    "took_ms": 0,
}

_SECRET_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{10,}|Bearer\s+\S+|api[_-]?key[\s=:]+\S+)", re.IGNORECASE
)


def log(message: str) -> None:
    """Short single-line log to stderr."""
    sys.stderr.write("[bridge {}] {}\n".format(time.strftime("%H:%M:%S"), message))
    sys.stderr.flush()


# --- context: data.local.json -> compact prompt block ----------------------


def load_local_data(base_dir: Path) -> "dict | None":
    """Read data.local.json from the runtime dir; None if absent or broken."""
    path = base_dir / DATA_FILE
    if not path.is_file():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError) as exc:
        log("data.local.json unreadable: {}".format(exc))
        return None
    return data if isinstance(data, dict) else None


def _fmt_num(value) -> str:
    if isinstance(value, float):
        return str(round(value, 1))
    return str(value)


def summarize_data(data: "dict | None") -> str:
    """Compact, prompt-ready digest of the dashboard data (capped length)."""
    if not data:
        return ""
    parts = []

    def add(label, value, unit=""):
        if value is not None:
            parts.append("{}: {}{}".format(label, _fmt_num(value), unit))

    add("Дата", data.get("date"))
    add("Recovery", data.get("recovery"), "%")
    add("HRV", data.get("hrv"), " ms")
    add("RHR", data.get("rhr"), " bpm")
    sleep, need = data.get("sleep"), data.get("sleepNeeded")
    if sleep is not None:
        parts.append(
            "Сон: {} ч{}".format(_fmt_num(sleep), " (цель {} ч)".format(_fmt_num(need)) if need else "")
        )
    add("Strain", data.get("strain"))

    for key, label in (("trendRec", "Recovery 14д"), ("trendHrv", "HRV 14д"), ("trendSleep", "Сон 14д")):
        trend = data.get(key)
        if isinstance(trend, list) and trend:
            vals = ",".join(_fmt_num(v) for v in trend[-14:] if isinstance(v, (int, float)))
            if vals:
                parts.append("{}: [{}]".format(label, vals))

    if isinstance(data.get("readiness"), str):
        parts.append("Готовность: {}".format(data["readiness"]))

    biomarkers = data.get("biomarkers")
    if isinstance(biomarkers, list) and biomarkers:
        items = "; ".join(
            "{} {}{} ({})".format(
                b.get("name", "?"), _fmt_num(b.get("value", "?")), b.get("unit") or "", b.get("status") or "?"
            )
            for b in biomarkers[:5]
            if isinstance(b, dict)
        )
        parts.append("Биомаркеры ({} шт.): {}".format(len(biomarkers), items))

    connections = data.get("connections")
    if isinstance(connections, dict):
        connected = [k for k, v in connections.items() if isinstance(v, dict) and v.get("connected")]
        if connected:
            parts.append("Источники: {}".format(", ".join(sorted(connected))))

    return "\n".join("- " + p for p in parts)[:MAX_SUMMARY_CHARS]


# --- prompt assembly --------------------------------------------------------


def sanitize_param(raw) -> str:
    """Collapse whitespace/control chars, cap length. Raises on non-strings."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("param must be a string")
    return " ".join(raw.split())[:MAX_PARAM_LEN]


def build_prompt(task: str, param: str = "", data_summary: str = "", lang: str = "ru") -> str:
    """Assemble the full agent prompt for a whitelisted task."""
    if task not in TASK_INSTRUCTIONS:
        raise ValueError("unknown task: {!r}".format(task))
    instruction = TASK_INSTRUCTIONS[task]
    if task == "research":
        instruction = instruction.format(topic=param or "HRV")

    blocks = [PROMPT_INTRO, PROMPT_SAFETY, instruction]
    if data_summary:
        blocks.append("ДАННЫЕ (выжимка из data.local.json):\n" + data_summary)
    else:
        blocks.append(
            "ДАННЫЕ: data.local.json не найден — реальных данных нет. Скажи это честно, "
            "не выдумывай значения; предложи, какие источники подключить."
        )
    blocks.append("Answer in English." if lang == "en" else "Отвечай по-русски, кратко, обычным текстом.")
    return "\n\n".join(blocks)


# --- agent runner ------------------------------------------------------------


def detect_agents() -> dict:
    """Which agent CLIs are available on PATH."""
    return {name: shutil.which(name) is not None for name in AGENT_BINARIES}


def _redact(text: str) -> str:
    return _SECRET_RE.sub("[redacted]", text)


def available_agents() -> list:
    """Agent CLIs present on this machine, in preference order."""
    return [name for name in ("claude", "codex") if shutil.which(name)]


def build_agent_command(agent: str, prompt: str, last_message_path: "str | None" = None) -> list:
    """argv for the agent CLI. The prompt travels as a single argv element —
    no shell is ever involved."""
    if agent == "claude":
        return ["claude", "-p", prompt, "--output-format", "text"]
    if agent == "codex":
        # --skip-git-repo-check: codex exec refuses to run outside a git repo
        # otherwise; --sandbox read-only: analysis only, no file writes;
        # --output-last-message: clean final answer without session logs.
        cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only"]
        if last_message_path:
            cmd.extend(["--output-last-message", last_message_path])
        cmd.append(prompt)
        return cmd
    raise ValueError("unknown agent: {!r}".format(agent))


def run_agent(prompt: str, base_dir: Path) -> dict:
    """Run agent CLIs in preference order; on failure fall through to the next.

    claude может быть установлен, но не авторизован для headless-вызова (401) —
    тогда честно пробуем codex, и только если упали все, возвращаем последнюю ошибку.
    """
    agents = available_agents()
    if not agents:
        return {"status": "no_agent", "message": "Установи Claude Code или Codex CLI"}

    last = None
    for agent in agents:
        last = _run_one_agent(agent, prompt, base_dir)
        if last.get("status") in ("ok", "timeout"):
            return last
    return last


def _run_one_agent(agent: str, prompt: str, base_dir: Path) -> dict:
    """One blocking CLI run with a timeout."""
    last_message_path = None
    if agent == "codex":
        fd, last_message_path = tempfile.mkstemp(prefix="oh-bridge-", suffix=".txt")
        os.close(fd)
    cmd = build_agent_command(agent, prompt, last_message_path)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=AGENT_TIMEOUT_S,
            cwd=str(base_dir),
            stdin=subprocess.DEVNULL,
        )
        took_ms = int((time.monotonic() - started) * 1000)
        if proc.returncode != 0:
            # CLIs report errors to stderr or stdout (e.g. auth failures) — take either tail.
            tail = ((proc.stderr or "").strip() or (proc.stdout or "").strip())[-MAX_STDERR_TAIL:]
            return {
                "status": "error",
                "agent": agent,
                "message": "exit {}: {}".format(proc.returncode, _redact(tail) or "no output"),
                "took_ms": took_ms,
            }
        result = (proc.stdout or "").strip()
        if last_message_path:  # codex: prefer the clean final message over the session log
            try:
                clean = Path(last_message_path).read_text(encoding="utf-8").strip()
                if clean:
                    result = clean
            except OSError:
                pass
        return {"status": "ok", "agent": agent, "result": result, "took_ms": took_ms}
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "agent": agent,
            "took_ms": int((time.monotonic() - started) * 1000),
        }
    except OSError as exc:
        return {"status": "error", "agent": agent, "message": _redact(str(exc))}
    finally:
        if last_message_path:
            try:
                os.unlink(last_message_path)
            except OSError:
                pass


def handle_agent_request(payload: dict, base_dir: Path) -> "tuple":
    """Validate the /api/agent payload and run the task. -> (http_status, body)."""
    if not isinstance(payload, dict):
        return 400, {"status": "error", "message": "body must be a JSON object"}

    task = payload.get("task")
    if task not in ALLOWED_TASKS:
        return 400, {
            "status": "error",
            "message": "unknown task; allowed: {}".format(", ".join(sorted(ALLOWED_TASKS))),
        }
    try:
        param = sanitize_param(payload.get("param"))
    except ValueError as exc:
        return 400, {"status": "error", "message": str(exc)}
    lang = payload.get("lang")
    lang = lang if lang in ("ru", "en") else "ru"

    if task == "transcript":
        return 200, dict(TRANSCRIPT_STUB)

    summary = summarize_data(load_local_data(base_dir))
    prompt = build_prompt(task, param=param, data_summary=summary, lang=lang)
    result = run_agent(prompt, base_dir)
    result["task"] = task
    return 200, result


# --- HTTP handler ------------------------------------------------------------


class BridgeHandler(SimpleHTTPRequestHandler):
    server_version = "OpenHealthBridge/0.1"
    protocol_version = "HTTP/1.1"

    @property
    def base_dir(self) -> Path:
        return Path(self.directory)

    def _send_json(self, body: dict, status: int = 200) -> None:
        raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/api/health":
            self._send_json({"ok": True, "agents": detect_agents()})
            return
        if path == "/api/data":
            data = load_local_data(self.base_dir)
            self._send_json(data if data is not None else {"demo": True})
            return
        super().do_GET()  # static files; index.html for directories

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path != "/api/agent":
            self._send_json({"status": "error", "message": "not found"}, status=404)
            return

        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self._send_json(
                {"status": "error", "message": "Content-Type must be application/json"}, status=415
            )
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            self._send_json({"status": "error", "message": "missing body"}, status=400)
            return
        if length > MAX_BODY_BYTES:
            self._send_json({"status": "error", "message": "body too large"}, status=413)
            return
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json({"status": "error", "message": "invalid JSON"}, status=400)
            return

        status, body = handle_agent_request(payload, self.base_dir)
        log(
            "POST /api/agent task={} -> {} ({} ms)".format(
                body.get("task", payload.get("task") if isinstance(payload, dict) else "?"),
                body.get("status"),
                body.get("took_ms", "-"),
            )
        )
        self._send_json(body, status=status)

    def log_message(self, fmt: str, *args) -> None:  # short stderr access log
        sys.stderr.write("[bridge] {} {}\n".format(self.address_string(), fmt % args))


# --- entrypoint --------------------------------------------------------------


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="OpenHealth dashboard bridge: static files + local agent runner (127.0.0.1 only)."
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port on 127.0.0.1 (default 8770)")
    parser.add_argument("--dir", default=".", help="directory with statics and data.local.json (default: cwd)")
    args = parser.parse_args(argv)

    base_dir = Path(args.dir).expanduser().resolve()
    if not base_dir.is_dir():
        parser.error("--dir is not a directory: {}".format(base_dir))

    handler = partial(BridgeHandler, directory=str(base_dir))
    try:
        server = ThreadingHTTPServer((HOST, args.port), handler)
    except OSError as exc:
        log("cannot bind {}:{} — {}".format(HOST, args.port, exc))
        sys.exit(1)

    agents = ", ".join(name for name, ok in detect_agents().items() if ok) or "none"
    log("serving http://{}:{}  dir={}  agents: {}".format(HOST, args.port, base_dir, agents))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        log("shutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
