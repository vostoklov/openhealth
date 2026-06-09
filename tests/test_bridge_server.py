"""Unit tests for the dashboard bridge server (ui/web/server.py).

No real agent CLIs are launched: shutil.which and subprocess.run are mocked.
The module is loaded by path because ui/web is not a package.
"""

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

_SERVER_PATH = Path(__file__).resolve().parent.parent / "ui" / "web" / "server.py"
_spec = importlib.util.spec_from_file_location("bridge_server", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)


# --- prompt assembly ---------------------------------------------------------


def test_build_prompt_insight_has_safety_and_data():
    prompt = server.build_prompt("insight", data_summary="- Recovery: 78%")
    assert "не врач" in prompt
    assert "C1-C5" in prompt
    assert "Recovery: 78%" in prompt
    assert "Отвечай по-русски" in prompt


def test_build_prompt_research_uses_param_with_default():
    assert "«сон»" in server.build_prompt("research", param="сон")
    assert "«HRV»" in server.build_prompt("research")  # default topic


def test_build_prompt_without_data_says_so():
    prompt = server.build_prompt("correlations")
    assert "data.local.json не найден" in prompt
    assert "не выдумывай" in prompt


def test_build_prompt_lang_en():
    assert "Answer in English." in server.build_prompt("insight", lang="en")


def test_build_prompt_rejects_unknown_task():
    with pytest.raises(ValueError):
        server.build_prompt("rm -rf /")


# --- param sanitizing --------------------------------------------------------


def test_sanitize_param_collapses_and_caps():
    assert server.sanitize_param("  a\n\tb   c ") == "a b c"
    assert len(server.sanitize_param("x" * 1000)) == server.MAX_PARAM_LEN
    assert server.sanitize_param(None) == ""


def test_sanitize_param_rejects_non_string():
    with pytest.raises(ValueError):
        server.sanitize_param({"cmd": "evil"})


# --- task whitelist via handle_agent_request ---------------------------------


@pytest.mark.parametrize("task", ["", "evil; rm -rf /", "insights", None, 42])
def test_whitelist_rejects_unknown_tasks(tmp_path, task):
    status, body = server.handle_agent_request({"task": task}, tmp_path)
    assert status == 400
    assert body["status"] == "error"


def test_whitelist_rejects_non_dict_body(tmp_path):
    status, body = server.handle_agent_request(["task", "insight"], tmp_path)
    assert status == 400


def test_transcript_is_honest_stub(tmp_path):
    status, body = server.handle_agent_request({"task": "transcript"}, tmp_path)
    assert status == 200
    assert body["status"] == "ok"
    assert body["stub"] is True
    assert "не подключён" in body["result"]


# --- data summary ------------------------------------------------------------


def test_summarize_data_compact_and_capped():
    data = {
        "date": "понедельник, 9 июня 2026",
        "recovery": 78,
        "hrv": 96,
        "rhr": 52,
        "sleep": 7.2,
        "sleepNeeded": 8.0,
        "trendRec": list(range(40)),  # only the last 14 should appear
        "readiness": "Recovery 78% (зелёная зона)",
        "biomarkers": [{"name": "Bifidobacterium", "value": 5, "unit": "%", "status": "ok"}],
        "connections": {"whoop": {"connected": True}, "oura": {"connected": False}},
    }
    text = server.summarize_data(data)
    assert "Recovery: 78%" in text
    assert "[26," in text and "25," not in text  # trend cut to the last 14
    assert "whoop" in text and "oura" not in text
    assert len(text) <= server.MAX_SUMMARY_CHARS
    assert server.summarize_data(None) == ""
    assert server.summarize_data({}) == ""


def test_load_local_data_reads_only_existing_valid_json(tmp_path):
    assert server.load_local_data(tmp_path) is None
    (tmp_path / server.DATA_FILE).write_text("{not json", encoding="utf-8")
    assert server.load_local_data(tmp_path) is None
    (tmp_path / server.DATA_FILE).write_text(json.dumps({"recovery": 70}), encoding="utf-8")
    assert server.load_local_data(tmp_path) == {"recovery": 70}


# --- agent runner (mocked subprocess) ----------------------------------------


def _which_factory(available):
    return lambda name: "/usr/bin/" + name if name in available else None


def test_run_agent_prefers_claude(tmp_path, monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="ответ агента\n", stderr="")

    monkeypatch.setattr(server.shutil, "which", _which_factory({"claude", "codex"}))
    monkeypatch.setattr(server.subprocess, "run", fake_run)

    out = server.run_agent("промпт с «кавычками» и $(дырками)", tmp_path)
    assert out["status"] == "ok"
    assert out["agent"] == "claude"
    assert out["result"] == "ответ агента"
    assert out["took_ms"] >= 0
    # prompt is a single argv element, no shell involved
    assert calls["cmd"] == ["claude", "-p", "промпт с «кавычками» и $(дырками)", "--output-format", "text"]
    assert "shell" not in calls["kwargs"] or calls["kwargs"]["shell"] is False
    assert calls["kwargs"]["timeout"] == server.AGENT_TIMEOUT_S


def test_run_agent_falls_back_to_codex(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        # codex writes the clean final answer into --output-last-message <file>
        out_file = cmd[cmd.index("--output-last-message") + 1]
        Path(out_file).write_text("чистый ответ", encoding="utf-8")
        return subprocess.CompletedProcess(cmd, 0, stdout="session log...\nчистый ответ", stderr="")

    monkeypatch.setattr(server.shutil, "which", _which_factory({"codex"}))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    out = server.run_agent("p", tmp_path)
    assert out["agent"] == "codex"
    assert out["status"] == "ok"
    assert out["result"] == "чистый ответ"  # file wins over the session log


def test_codex_command_is_safe_and_prompt_is_last():
    cmd = server.build_agent_command("codex", "промпт", "/tmp/x.txt")
    assert cmd[0:2] == ["codex", "exec"]
    assert "--skip-git-repo-check" in cmd
    assert cmd[cmd.index("--sandbox") + 1] == "read-only"
    assert cmd[-1] == "промпт"  # single argv element, no shell


def test_run_agent_no_agent(tmp_path, monkeypatch):
    monkeypatch.setattr(server.shutil, "which", _which_factory(set()))
    out = server.run_agent("p", tmp_path)
    assert out["status"] == "no_agent"
    assert "Claude Code" in out["message"]


def test_run_agent_timeout(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(server.shutil, "which", _which_factory({"claude"}))
    monkeypatch.setattr(server.subprocess, "run", fake_run)
    out = server.run_agent("p", tmp_path)
    assert out["status"] == "timeout"
    assert out["agent"] == "claude"


def test_run_agent_cli_error_returns_redacted_stderr_tail(tmp_path, monkeypatch):
    stderr = "boom\napi_key=sk-secret1234567890abc\n" + "x" * 1000
    monkeypatch.setattr(server.shutil, "which", _which_factory({"claude"}))
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="", stderr=stderr),
    )
    out = server.run_agent("p", tmp_path)
    assert out["status"] == "error"
    assert "sk-secret" not in out["message"]
    assert len(out["message"]) <= server.MAX_STDERR_TAIL + 32  # tail + "exit 1: " prefix


def test_run_agent_cli_error_falls_back_to_stdout_tail(tmp_path, monkeypatch):
    # e.g. claude prints auth errors to stdout, stderr stays empty
    monkeypatch.setattr(server.shutil, "which", _which_factory({"claude"}))
    monkeypatch.setattr(
        server.subprocess,
        "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, stdout="API Error: 401", stderr=""),
    )
    out = server.run_agent("p", tmp_path)
    assert out["status"] == "error"
    assert "401" in out["message"]


def test_handle_agent_request_runs_insight_with_data(tmp_path, monkeypatch):
    (tmp_path / server.DATA_FILE).write_text(json.dumps({"recovery": 64}), encoding="utf-8")
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["prompt"] = cmd[2]  # claude -p <prompt> ...
        return subprocess.CompletedProcess(cmd, 0, stdout="наблюдения", stderr="")

    monkeypatch.setattr(server.shutil, "which", _which_factory({"claude"}))
    monkeypatch.setattr(server.subprocess, "run", fake_run)

    status, body = server.handle_agent_request({"task": "insight", "lang": "ru"}, tmp_path)
    assert status == 200
    assert body["status"] == "ok"
    assert body["task"] == "insight"
    assert "Recovery: 64%" in seen["prompt"]
    assert "не врач" in seen["prompt"]
