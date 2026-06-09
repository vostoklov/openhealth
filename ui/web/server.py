#!/usr/bin/env python3
"""OpenHealth dashboard bridge — static server + local AI agent runner.

The "agency" front of the dashboard: serves the dashboard statics, exposes the
local data file and can run a local AI agent CLI (Claude Code / Codex) over the
user's local data, returning the result to the page.

stdlib only (repo rule): argparse, http.server, json, subprocess, shutil, pathlib.

Endpoints:
    GET  /            -> static files from --dir (index.html by default)
    GET  /api/data    -> data.local.json from --dir (200), or {"demo": true}
    GET  /api/behaviors -> openhealth/data/journal_behaviors.json (full WHOOP-style
                          behavior catalog, cached in memory; 404 if missing)
    GET  /api/providers -> openhealth/data/providers.json (device/data provider
                          catalog for the "Источники данных" screen; cached)
    GET  /api/health  -> {"ok": true, "agents": {"claude": bool, "codex": bool,
                          "openhealth": bool}}
    GET  /api/config  -> {"config": {...agent.json...}, "agents": [{"name",
                          "binary", "available", "selectable"}, ...]}
    POST /api/config  -> {"agent": "auto|claude|codex|antigravity",
                          "model": "name-or-null"}; both keys optional,
                          whitelist-validated, persisted to
                          ~/.openhealth/agent.json (mode 0600).
    GET  /api/memory  -> {"entries": [last 30, newest first], "count": N}
    DELETE /api/memory -> wipe agent memory; {"status": "ok", "cleared": N}
    GET  /api/calendar?date=YYYY-MM-DD -> day load from the ICS subscription
                          (live fetch, 10 min in-memory cache). Without a
                          configured feed: {"configured": false, "how": [...]}.
    POST /api/calendar -> {"ics_url": "https://...ics"}; validated and saved
                          to ~/.openhealth/calendar.json (0600). The URL is a
                          secret: never logged, never echoed back.
    DELETE /api/calendar -> disable the subscription (URL kept for re-enable)
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

Agent prompts are assembled from: intro + safety rules + user context preamble
(AGENTS.md/CLAUDE.md, goal*/about-me* docs, research/ folder — see
build_user_context) + memory of past runs (openhealth.agent_memory) + the task
instruction + a digest of data.local.json.

Security model:
    - binds to 127.0.0.1 only;
    - task names come from a fixed whitelist; param is a plain string,
      whitespace-collapsed and capped at 200 chars;
    - agent/model selection is whitelist+regex validated; config and memory
      live under ~/.openhealth (outside any repo) with 0600/0700 modes;
    - the prompt is passed to the CLI as a single argv element, never through
      a shell (no shell=True anywhere);
    - POST must be application/json with body <= 64 KB;
    - same-origin usage only, no CORS headers on purpose.

PRIVACY: data.local.json holds real personal health data and lives in the
runtime directory (--dir), never in the repo. Agent memory holds condensed
personal conclusions and lives in ~/.openhealth/memory — never logged, never
in the repo. This file contains no data.

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
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

_REPO_ROOT = Path(__file__).resolve().parents[2]
try:
    from openhealth import agent_memory
    from openhealth.connectors import ics_calendar
except ImportError:  # running from a checkout without `pip install -e .`
    sys.path.insert(0, str(_REPO_ROOT))
    from openhealth import agent_memory
    from openhealth.connectors import ics_calendar

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

# --- agent selection config (~/.openhealth/agent.json) ----------------------

CONFIG_FILE = "agent.json"
# task config "agent" values the user may choose; "auto" keeps the cascade
SELECTABLE_AGENTS = ("auto", "claude", "codex", "antigravity")
# every agent CLI we know how to detect; antigravity ships the `agy` binary.
# hermes/openclaw are detected and reported, but not runnable yet.
AGENT_CLI = {
    "claude": "claude",
    "codex": "codex",
    "antigravity": "agy",
    "hermes": "hermes",
    "openclaw": "openclaw",
}
DEFAULT_AGENT_CONFIG = {"agent": "auto", "model": None, "extra_args": []}
MAX_MODEL_LEN = 100
MAX_EXTRA_ARGS = 16
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,%d}$" % (MAX_MODEL_LEN - 1))

# --- user context preamble limits -------------------------------------------

MAX_CONTEXT_CHARS = 4000  # whole preamble cap
CONTEXT_AGENTS_CHARS = 2000  # AGENTS.md / CLAUDE.md excerpt
CONTEXT_DOC_CHARS = 600  # goal* / about-me* excerpts, each
CONTEXT_RESEARCH_FRESH = 3  # how many freshest research files to excerpt
CONTEXT_RESEARCH_HEAD_CHARS = 260  # excerpt size per research file
CONTEXT_RESEARCH_MAX_NAMES = 12
MAX_MEMORY_BLOCK_CHARS = agent_memory.MAX_MEMORY_BLOCK_CHARS  # 1200

CONTEXT_HEADER = (
    "КОНТЕКСТ ПОЛЬЗОВАТЕЛЯ. Обязательно учитывай инструкции и личные "
    "исследования пользователя ниже. Если они противоречат общим знаниям — "
    "отдай приоритет личным данным и инструкциям, явно пометив это в ответе."
)

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


# --- agent config: ~/.openhealth/agent.json ----------------------------------


def config_home() -> Path:
    """~/.openhealth, overridable via OPENHEALTH_HOME (tests, portable setups)."""
    return Path(os.environ.get("OPENHEALTH_HOME") or "~/.openhealth").expanduser()


def agent_config_path() -> Path:
    return config_home() / CONFIG_FILE


def sanitize_model(raw) -> "str | None":
    """None/empty -> None; otherwise a strict model-name pattern or ValueError."""
    if raw is None:
        return None
    if not isinstance(raw, str):
        raise ValueError("model must be a string or null")
    raw = raw.strip()
    if not raw:
        return None
    if not _MODEL_RE.match(raw):
        raise ValueError("model: only letters, digits, . _ : / - (max {} chars)".format(MAX_MODEL_LEN))
    return raw


def load_agent_config() -> dict:
    """Read and validate agent.json; silently fall back to safe defaults."""
    cfg = {"agent": "auto", "model": None, "extra_args": []}
    path = agent_config_path()
    if not path.is_file():
        return cfg
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log("agent.json unreadable, using defaults: {}".format(exc))
        return cfg
    if not isinstance(raw, dict):
        return cfg
    if raw.get("agent") in SELECTABLE_AGENTS:
        cfg["agent"] = raw["agent"]
    try:
        cfg["model"] = sanitize_model(raw.get("model"))
    except ValueError:
        cfg["model"] = None
    extra = raw.get("extra_args")
    if isinstance(extra, list):
        cfg["extra_args"] = [str(a)[:MAX_PARAM_LEN] for a in extra[:MAX_EXTRA_ARGS] if isinstance(a, str)]
    return cfg


def save_agent_config(cfg: dict) -> Path:
    """Persist agent.json privately (dir 0700, file 0600). Returns the path."""
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    path = agent_config_path()
    tmp = path.with_name(path.name + ".tmp")
    body = {
        "agent": cfg.get("agent", "auto"),
        "model": cfg.get("model"),
        "extra_args": list(cfg.get("extra_args") or []),
    }
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def agents_status() -> list:
    """Every known agent CLI with availability and selectability flags."""
    return [
        {
            "name": name,
            "binary": binary,
            "available": shutil.which(binary) is not None,
            "selectable": name in SELECTABLE_AGENTS,
        }
        for name, binary in AGENT_CLI.items()
    ]


def handle_config_request(payload) -> "tuple":
    """Validate POST /api/config body and persist. -> (http_status, body)."""
    if not isinstance(payload, dict):
        return 400, {"status": "error", "message": "body must be a JSON object"}
    cfg = load_agent_config()
    changed = False
    if "agent" in payload:
        agent = payload["agent"]
        if agent not in SELECTABLE_AGENTS:
            return 400, {
                "status": "error",
                "message": "unknown agent; allowed: {}".format(", ".join(SELECTABLE_AGENTS)),
            }
        cfg["agent"] = agent
        changed = True
    if "model" in payload:
        try:
            cfg["model"] = sanitize_model(payload["model"])
        except ValueError as exc:
            return 400, {"status": "error", "message": str(exc)}
        changed = True
    if changed:
        try:
            save_agent_config(cfg)
        except OSError as exc:
            return 500, {"status": "error", "message": "cannot write config: {}".format(exc)}
    return 200, {"status": "ok", "config": cfg, "agents": agents_status()}


# --- static catalogs: behaviors + providers (repo data, cached in memory) ---

_CATALOG_FILES = {
    "behaviors": _REPO_ROOT / "openhealth" / "data" / "journal_behaviors.json",
    "providers": _REPO_ROOT / "openhealth" / "data" / "providers.json",
}
_catalog_cache = {}
_catalog_cache_lock = threading.Lock()


def load_catalog(name: str) -> "dict | None":
    """Static JSON catalog from the repo; read once, kept in memory.

    These files are versioned reference data (no personal content), so a
    process-lifetime cache is safe; restart the bridge to pick up edits.
    """
    with _catalog_cache_lock:
        if name in _catalog_cache:
            return _catalog_cache[name]
    path = _CATALOG_FILES.get(name)
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log("catalog {} unreadable: {}".format(name, exc.__class__.__name__))
        return None
    if not isinstance(data, dict):
        return None
    with _catalog_cache_lock:
        _catalog_cache[name] = data
    return data


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


# --- user context preamble: AGENTS.md / goal / about-me / research ----------


def _context_dirs(base_dir: Path) -> list:
    """Where personal docs are looked up: the runtime dir, then its parent."""
    dirs = [base_dir]
    if base_dir.parent != base_dir:
        dirs.append(base_dir.parent)
    return dirs


def _read_head(path: Path, limit: int) -> str:
    """First ``limit`` characters of a text file; '' on any read problem."""
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            return fh.read(limit).strip()
    except OSError:
        return ""


def _find_exact(base_dir: Path, names) -> "Path | None":
    for directory in _context_dirs(base_dir):
        for name in names:
            candidate = directory / name
            if candidate.is_file():
                return candidate
    return None


def _find_doc_by_stem(base_dir: Path, stem: str) -> "Path | None":
    """Case-insensitive `<stem>.md`, else the first `<stem>*.md` (e.g. GOAL-x.md)."""
    for directory in _context_dirs(base_dir):
        try:
            files = sorted(
                p for p in directory.iterdir() if p.is_file() and p.suffix.lower() == ".md"
            )
        except OSError:
            continue
        exact = [p for p in files if p.name.lower() == stem + ".md"]
        if exact:
            return exact[0]
        prefixed = [p for p in files if p.name.lower().startswith(stem)]
        if prefixed:
            return prefixed[0]
    return None


def _find_research_dir(base_dir: Path) -> "Path | None":
    for directory in _context_dirs(base_dir):
        for name in ("research", "researches"):
            candidate = directory / name
            if candidate.is_dir():
                return candidate
    return None


def _research_section(base_dir: Path) -> str:
    research_dir = _find_research_dir(base_dir)
    if research_dir is None:
        return ""
    try:
        files = [
            p
            for p in research_dir.iterdir()
            if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in (".md", ".txt")
        ]
    except OSError:
        return ""
    if not files:
        return ""
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    lines = ["Личные ресёрчи пользователя ({}/) — опирайся на них:".format(research_dir.name)]
    names = ", ".join(p.name for p in files[:CONTEXT_RESEARCH_MAX_NAMES])
    if len(files) > CONTEXT_RESEARCH_MAX_NAMES:
        names += ", … (+{})".format(len(files) - CONTEXT_RESEARCH_MAX_NAMES)
    lines.append("Файлы: " + names)
    for path in files[:CONTEXT_RESEARCH_FRESH]:
        head = " ".join(_read_head(path, CONTEXT_RESEARCH_HEAD_CHARS).split())
        if head:
            lines.append("- {}: {}".format(path.name, head))
    return "\n".join(lines)


def build_user_context(base_dir: Path) -> str:
    """Personal-context preamble for agent prompts.

    Sources (looked up in --dir, then its parent):
      1. AGENTS.md or CLAUDE.md  — user instructions, first ~2000 chars;
      2. goal.md / goal*.md      — project goal, ~600 chars;
      3. about-me.md / about-me* — personal background, ~600 chars;
      4. research|researches/    — file names + heads of the 3 freshest.

    Total capped at MAX_CONTEXT_CHARS; on overflow the tail sections
    (research first) lose space, AGENTS.md keeps priority.
    Returns '' when nothing personal is found.
    """
    sections = []

    agents_file = _find_exact(base_dir, ("AGENTS.md", "CLAUDE.md"))
    if agents_file is not None:
        text = _read_head(agents_file, CONTEXT_AGENTS_CHARS)
        if text:
            sections.append("Инструкции пользователя ({}):\n{}".format(agents_file.name, text))

    for stem, label in (("goal", "Цель пользователя"), ("about-me", "О пользователе")):
        doc = _find_doc_by_stem(base_dir, stem)
        if doc is not None:
            text = _read_head(doc, CONTEXT_DOC_CHARS)
            if text:
                sections.append("{} ({}):\n{}".format(label, doc.name, text))

    research = _research_section(base_dir)
    if research:
        sections.append(research)

    if not sections:
        return ""

    budget = MAX_CONTEXT_CHARS - len(CONTEXT_HEADER)
    kept = []
    for section in sections:  # priority order: AGENTS > goal > about-me > research
        if budget <= 2:
            break
        piece = section[: budget - 2]
        kept.append(piece)
        budget -= len(piece) + 2
    return (CONTEXT_HEADER + "\n\n" + "\n\n".join(kept))[:MAX_CONTEXT_CHARS]


# --- prompt assembly --------------------------------------------------------


def sanitize_param(raw) -> str:
    """Collapse whitespace/control chars, cap length. Raises on non-strings."""
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ValueError("param must be a string")
    return " ".join(raw.split())[:MAX_PARAM_LEN]


def build_prompt(
    task: str,
    param: str = "",
    data_summary: str = "",
    lang: str = "ru",
    user_context: str = "",
    memory_block: str = "",
) -> str:
    """Assemble the full agent prompt for a whitelisted task.

    Order: intro, safety, user context preamble, memory of past runs,
    the task itself, the data digest, language hint. The preamble goes
    BEFORE the task so personal instructions take precedence.
    """
    if task not in TASK_INSTRUCTIONS:
        raise ValueError("unknown task: {!r}".format(task))
    instruction = TASK_INSTRUCTIONS[task]
    if task == "research":
        instruction = instruction.format(topic=param or "HRV")

    blocks = [PROMPT_INTRO, PROMPT_SAFETY]
    if user_context:
        blocks.append(user_context)
    if memory_block:
        blocks.append(memory_block)
    blocks.append(instruction)
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


def build_agent_command(
    agent: str,
    prompt: str,
    last_message_path: "str | None" = None,
    model: "str | None" = None,
    extra_args: "tuple | list" = (),
) -> list:
    """argv for the agent CLI. The prompt travels as a single argv element —
    no shell is ever involved. Model flags per CLI: claude `--model X`,
    codex `-m X`, antigravity (agy) `--model X` (verified via `agy --help`)."""
    extra = [str(a) for a in extra_args]
    if agent == "claude":
        cmd = ["claude", "-p", prompt, "--output-format", "text"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(extra)
        return cmd
    if agent == "codex":
        # --skip-git-repo-check: codex exec refuses to run outside a git repo
        # otherwise; --sandbox read-only: analysis only, no file writes;
        # --output-last-message: clean final answer without session logs.
        cmd = ["codex", "exec", "--skip-git-repo-check", "--sandbox", "read-only"]
        if model:
            cmd.extend(["-m", model])
        cmd.extend(extra)
        if last_message_path:
            cmd.extend(["--output-last-message", last_message_path])
        cmd.append(prompt)
        return cmd
    if agent == "antigravity":
        # agy uses Go-style flags: all flags before the prompt value;
        # --print <prompt> runs one prompt non-interactively.
        cmd = ["agy"]
        if model:
            cmd.extend(["--model", model])
        cmd.extend(extra)
        cmd.extend(["--print", prompt])
        return cmd
    raise ValueError("unknown agent: {!r}".format(agent))


def run_agent(prompt: str, base_dir: Path, config: "dict | None" = None) -> dict:
    """Run agent CLIs honoring ~/.openhealth/agent.json.

    agent=auto keeps the cascade (claude -> codex): claude может быть
    установлен, но не авторизован для headless-вызова (401) — тогда честно
    пробуем codex, и только если упали все, возвращаем последнюю ошибку.
    A concrete agent in the config runs alone, no fallback.
    """
    config = config if config is not None else load_agent_config()
    choice = config.get("agent") or "auto"
    if choice == "auto":
        agents = available_agents()
        if not agents:
            return {"status": "no_agent", "message": "Установи Claude Code или Codex CLI"}
    else:
        binary = AGENT_CLI.get(choice)
        if binary is None or shutil.which(binary) is None:
            return {
                "status": "no_agent",
                "message": "Выбранный агент '{}' недоступен (CLI `{}` не найден). "
                "Поменяй выбор в настройках или поставь CLI.".format(choice, binary or choice),
            }
        agents = [choice]

    model = config.get("model")
    extra_args = tuple(config.get("extra_args") or ())
    last = None
    for agent in agents:
        last = _run_one_agent(agent, prompt, base_dir, model=model, extra_args=extra_args)
        if last.get("status") in ("ok", "timeout"):
            return last
    return last


def _run_one_agent(
    agent: str,
    prompt: str,
    base_dir: Path,
    model: "str | None" = None,
    extra_args: "tuple | list" = (),
) -> dict:
    """One blocking CLI run with a timeout."""
    last_message_path = None
    if agent == "codex":
        fd, last_message_path = tempfile.mkstemp(prefix="oh-bridge-", suffix=".txt")
        os.close(fd)
    cmd = build_agent_command(agent, prompt, last_message_path, model=model, extra_args=extra_args)

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
    user_context = build_user_context(base_dir)
    memory_block = ""
    try:
        past = agent_memory.recall(task, query=param, limit=5)
        memory_block = agent_memory.format_memory_block(past, max_chars=MAX_MEMORY_BLOCK_CHARS)
    except OSError:
        pass  # memory unavailable -> run without it
    # sizes only — never the contents (personal data)
    log("prompt preamble: context {} chars, memory {} chars".format(len(user_context), len(memory_block)))

    prompt = build_prompt(
        task,
        param=param,
        data_summary=summary,
        lang=lang,
        user_context=user_context,
        memory_block=memory_block,
    )
    result = run_agent(prompt, base_dir, config=load_agent_config())
    result["task"] = task
    if result.get("status") == "ok" and result.get("result"):
        try:
            agent_memory.remember(task, result["result"], tags=[param] if param else [])
        except OSError as exc:
            log("memory write failed: {}".format(exc.__class__.__name__))
    return 200, result


# --- calendar: ICS subscription -> day load ----------------------------------

CALENDAR_CACHE_TTL_S = 600  # live feed, refetched at most every 10 minutes
_CALENDAR_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CALENDAR_HOW = [
    "Google Calendar: Settings → нужный календарь → 'Integrate calendar' → "
    "скопируй 'Secret address in iCal format' (ссылка на .ics).",
    "Apple iCloud: Календарь → правый клик по календарю → 'Public Calendar' → скопируй webcal://-ссылку.",
    "Сохрани её: POST /api/calendar c JSON {\"ics_url\": \"<ссылка>\"}. "
    "URL секретный — хранится только локально в ~/.openhealth/calendar.json.",
]

_calendar_cache = {"url": None, "fetched_at": 0.0, "parsed": None}
_calendar_cache_lock = threading.Lock()


def get_calendar_parsed(url: str) -> "tuple":
    """Parsed feed for ``url`` -> (parsed, served_from_cache). May raise IcsCalendarError."""
    now = time.monotonic()
    with _calendar_cache_lock:
        fresh = (
            _calendar_cache["parsed"] is not None
            and _calendar_cache["url"] == url
            and now - _calendar_cache["fetched_at"] < CALENDAR_CACHE_TTL_S
        )
        if fresh:
            return _calendar_cache["parsed"], True
    text = ics_calendar.fetch_ics(url)  # network call outside the lock
    parsed = ics_calendar.parse_ics(text)
    with _calendar_cache_lock:
        _calendar_cache.update({"url": url, "fetched_at": time.monotonic(), "parsed": parsed})
    return parsed, False


def invalidate_calendar_cache() -> None:
    with _calendar_cache_lock:
        _calendar_cache.update({"url": None, "fetched_at": 0.0, "parsed": None})


def handle_calendar_get(date_str: "str | None" = None) -> "tuple":
    """GET /api/calendar[?date=YYYY-MM-DD] -> (http_status, body)."""
    if date_str is not None:
        if not _CALENDAR_DATE_RE.match(date_str):
            return 400, {"status": "error", "message": "date must be YYYY-MM-DD"}
        try:
            time.strptime(date_str, "%Y-%m-%d")  # rejects 2026-13-99 etc.
        except ValueError:
            return 400, {"status": "error", "message": "date must be a real YYYY-MM-DD date"}
    config = ics_calendar.load_calendar_config()
    if not config or not config.get("enabled"):
        return 200, {"configured": False, "how": CALENDAR_HOW}
    day = date_str or time.strftime("%Y-%m-%d")
    try:
        parsed, cached = get_calendar_parsed(config["ics_url"])
    except ics_calendar.IcsCalendarError as exc:
        # exc messages never contain the secret URL (see ics_calendar)
        return 200, {"configured": True, "status": "error", "message": str(exc)}
    return 200, {
        "configured": True,
        "status": "ok",
        "cached": cached,
        "events_total": len(parsed.get("events", [])),
        "warnings": parsed.get("warnings", [])[:10],
        "day": ics_calendar.day_load(parsed.get("events", []), day),
    }


def handle_todos_get(date_str: "str | None" = None) -> "tuple":
    """GET /api/todos[?date=YYYY-MM-DD] -> (status, {completed[], candidates[]}).

    Закрытые задачи Todoist за день + кандидаты в журнал здоровья.
    Без токена — честный 503 с инструкцией (контракт connectors/todoist.py).
    """
    if date_str is not None:
        if not _CALENDAR_DATE_RE.match(date_str):
            return 400, {"status": "error", "message": "date must be YYYY-MM-DD"}
        try:
            time.strptime(date_str, "%Y-%m-%d")
        except ValueError:
            return 400, {"status": "error", "message": "date must be a real YYYY-MM-DD date"}
    day = date_str or time.strftime("%Y-%m-%d")
    try:
        from openhealth.connectors import todoist
    except ImportError:
        return 200, {"configured": False, "message": "коннектор todoist недоступен в этой установке"}
    try:
        completed = todoist.fetch_completed(day)
    except todoist.TodoistNotConfigured as exc:
        return 503, {"configured": False, "message": str(exc)}
    except Exception as exc:  # сеть/HTTP — честная ошибка без падения сервера
        return 200, {"configured": True, "status": "error", "message": exc.__class__.__name__}
    return 200, {
        "configured": True,
        "status": "ok",
        "completed": completed,
        "candidates": todoist.health_candidates(completed),
    }


def handle_calendar_post(payload) -> "tuple":
    """POST /api/calendar {"ics_url": ...} -> (http_status, body). URL is never echoed."""
    if not isinstance(payload, dict):
        return 400, {"status": "error", "message": "body must be a JSON object"}
    try:
        ics_calendar.save_calendar_config(payload.get("ics_url"), enabled=True)
    except ics_calendar.IcsCalendarError as exc:
        return 400, {"status": "error", "message": str(exc)}
    except OSError as exc:
        return 500, {"status": "error", "message": "cannot write config: {}".format(exc.__class__.__name__)}
    invalidate_calendar_cache()
    return 200, {"status": "ok", "configured": True}


def handle_calendar_delete() -> "tuple":
    """DELETE /api/calendar -> disable the subscription, keep the URL on disk."""
    try:
        was_configured = ics_calendar.disable_calendar_config()
    except (ics_calendar.IcsCalendarError, OSError):
        return 500, {"status": "error", "message": "cannot update calendar config"}
    invalidate_calendar_cache()
    return 200, {"status": "ok", "configured": False, "was_configured": was_configured}


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
        if path == "/api/config":
            self._send_json({"config": load_agent_config(), "agents": agents_status()})
            return
        if path == "/api/memory":
            entries = agent_memory.load_entries()
            self._send_json(
                {"entries": list(reversed(entries[-agent_memory.DIGEST_ENTRIES:])), "count": len(entries)}
            )
            return
        if path == "/api/data":
            data = load_local_data(self.base_dir)
            self._send_json(data if data is not None else {"demo": True})
            return
        if path in ("/api/behaviors", "/api/providers"):
            name = path.rsplit("/", 1)[1]
            catalog = load_catalog(name)
            if catalog is None:
                self._send_json(
                    {"status": "error", "message": "{}.json не найден в репозитории".format(name)},
                    status=404,
                )
                return
            self._send_json(catalog)
            return
        if path == "/api/calendar":
            query = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            status, body = handle_calendar_get(query.get("date", [None])[0])
            self._send_json(body, status=status)
            return
        if path == "/api/todos":
            query = parse_qs(self.path.split("?", 1)[1]) if "?" in self.path else {}
            status, body = handle_todos_get(query.get("date", [None])[0])
            self._send_json(body, status=status)
            return
        super().do_GET()  # static files; index.html for directories

    def _read_json_body(self) -> "tuple":
        """-> (payload, None) or (None, (http_status, error_body))."""
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            return None, (415, {"status": "error", "message": "Content-Type must be application/json"})
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0:
            return None, (400, {"status": "error", "message": "missing body"})
        if length > MAX_BODY_BYTES:
            return None, (413, {"status": "error", "message": "body too large"})
        try:
            return json.loads(self.rfile.read(length).decode("utf-8")), None
        except (ValueError, UnicodeDecodeError):
            return None, (400, {"status": "error", "message": "invalid JSON"})

    def do_POST(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path not in ("/api/agent", "/api/config", "/api/calendar"):
            self._send_json({"status": "error", "message": "not found"}, status=404)
            return

        payload, error = self._read_json_body()
        if error is not None:
            self._send_json(error[1], status=error[0])
            return

        if path == "/api/calendar":
            status, body = handle_calendar_post(payload)
            # only the outcome — never the URL (it is a secret)
            log("POST /api/calendar -> {}".format(body.get("status")))
            self._send_json(body, status=status)
            return

        if path == "/api/config":
            status, body = handle_config_request(payload)
            log("POST /api/config -> {} (agent={})".format(
                body.get("status"), (body.get("config") or {}).get("agent", "-")
            ))
            self._send_json(body, status=status)
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

    def do_DELETE(self) -> None:  # noqa: N802 (http.server API)
        path = self.path.split("?", 1)[0]
        if path == "/api/calendar":
            status, body = handle_calendar_delete()
            log("DELETE /api/calendar -> {}".format(body.get("status")))
            self._send_json(body, status=status)
            return
        if path != "/api/memory":
            self._send_json({"status": "error", "message": "not found"}, status=404)
            return
        try:
            cleared = agent_memory.clear()
        except OSError:
            self._send_json({"status": "error", "message": "cannot clear memory"}, status=500)
            return
        log("DELETE /api/memory -> cleared {} entries".format(cleared))
        self._send_json({"status": "ok", "cleared": cleared})

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
