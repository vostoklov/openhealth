"""Todoist connector — completed tasks become health-journal candidates.

Todo services are a low-friction evidence source: when you close "Тренировка"
or "Morning run" in Todoist, that is a real, dated behavior signal worth a
journal entry. This connector pulls:

* ``fetch_completed(date)``    — tasks completed on one day (Sync API v9
  ``completed/get_all``, paginated), each as ``{content, completed_at,
  project, labels}``.
* ``fetch_today_tasks()``      — active tasks due today (REST API v2), as
  schedule-load context.
* ``health_candidates(tasks)`` — keyword filter (RU + EN word-prefix stems,
  plus ``health``/``fitness`` labels) that turns raw tasks into journal
  *candidates* for human review — suggestions, never auto-logged facts.

Auth is the personal API token (PAT — the lowest-friction route, no OAuth app
needed for your own data): Todoist Settings → Integrations → Developer → API
token. Set ``OPENHEALTH_TODOIST_TOKEN`` or write the token to
``~/.openhealth/todoist.token``. Without a token every fetch raises
``TodoistNotConfigured`` carrying the same instructions — no silent empties.

Pure stdlib (urllib), local-first: the only network peer is api.todoist.com.
Keyword matching is deliberately recall-leaning (word-prefix stems), so a few
false positives like "анализ данных" can surface — a human decides what
actually enters the journal.
"""

import json
import os
import re
from datetime import date as _date
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

TODOIST_REST_API = "https://api.todoist.com/rest/v2"
TODOIST_SYNC_COMPLETED_URL = "https://api.todoist.com/sync/v9/completed/get_all"
TODOIST_TOKEN_ENV = "OPENHEALTH_TODOIST_TOKEN"
TODOIST_TOKEN_PATH = Path.home() / ".openhealth" / "todoist.token"

# Sync API caps completed/get_all pages at 200 items.
COMPLETED_PAGE_LIMIT = 200

TOKEN_HOWTO = (
    "Todoist token is not configured. Get a personal API token (PAT) in 3 steps:\n"
    "  1. Open Todoist → Settings → Integrations → Developer tab.\n"
    "  2. Copy the 'API token' shown there (personal token, no OAuth app needed).\n"
    "  3. Export %s=<token> or write it to %s.\n"
    "The token grants full account access — keep it local, never commit it."
    % (TODOIST_TOKEN_ENV, TODOIST_TOKEN_PATH)
)

# Word-prefix stems → Russian journal labels. Extend freely: a stem matches
# when any word in the task content *starts with* it (so "тренир" catches
# "тренировка"/"тренируюсь" but "сон" does not fire on "сезон").
HEALTH_KEYWORDS: Dict[str, str] = {
    # RU stems
    "тренир": "тренировка",
    "спорт": "спорт",
    "зал": "зал",
    "бег": "бег",
    "йог": "йога",
    "массаж": "массаж",
    "врач": "врач",
    "стоматолог": "врач",
    "анализ": "анализы",
    "сон": "сон",
    "медит": "медитация",
    "прогул": "прогулка",
    "плаван": "плавание",
    "витамин": "витамины",
    "лекарств": "лекарства",
    "растяж": "растяжка",
    # EN stems
    "walk": "прогулка",
    "run": "бег",
    "gym": "зал",
    "workout": "тренировка",
    "yoga": "йога",
    "doctor": "врач",
    "sleep": "сон",
    "meditat": "медитация",
    "swim": "плавание",
    "stretch": "растяжка",
}

# Task labels that mark a task as health-relevant even without a keyword hit.
HEALTH_LABELS: Dict[str, str] = {
    "health": "здоровье",
    "fitness": "фитнес",
    "здоровье": "здоровье",
    "спорт": "спорт",
}

_WORD_RE = re.compile(r"[a-zа-яё0-9]+")


class TodoistError(RuntimeError):
    """Raised when a Todoist API call fails."""


class TodoistNotConfigured(TodoistError):
    """Raised when no Todoist token is available; message explains how to get one."""


def load_todoist_token() -> str:
    """Return the personal API token from env or ``~/.openhealth/todoist.token``.

    Raises ``TodoistNotConfigured`` (with the how-to text) when neither exists.
    """
    token = (os.getenv(TODOIST_TOKEN_ENV) or "").strip()
    if token:
        return token
    try:
        if TODOIST_TOKEN_PATH.exists():
            token = TODOIST_TOKEN_PATH.read_text(encoding="utf-8").strip()
            if token:
                return token
    except OSError:
        pass
    raise TodoistNotConfigured(TOKEN_HOWTO)


def fetch_completed(date: Union[str, _date], token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Tasks completed on one calendar day, normalized for the journal pipeline.

    Uses Sync API v9 ``completed/get_all`` (the REST API does not expose
    completed history) with ``annotate_items=true`` so labels survive, and
    paginates via offset when a day holds more than one page. Returns::

        [{"content": str, "completed_at": str, "project": str|None, "labels": [str, ...]}, ...]
    """
    day = _normalize_date(date)
    token = token or load_todoist_token()
    items: List[Dict[str, Any]] = []
    rest_projects: Optional[Dict[str, str]] = None
    offset = 0
    while True:
        payload = _http_get_json(
            TODOIST_SYNC_COMPLETED_URL,
            token,
            query={
                "since": "%sT00:00:00" % day,
                "until": "%sT23:59:59" % day,
                "limit": COMPLETED_PAGE_LIMIT,
                "offset": offset,
                "annotate_items": "true",
            },
        )
        if not isinstance(payload, dict):
            raise TodoistError("Todoist completed/get_all returned a non-object payload")
        page = payload.get("items") or []
        payload_projects = payload.get("projects") or {}
        for raw in page:
            project_id = str(raw.get("project_id") or "")
            project_name = None
            if project_id:
                entry = payload_projects.get(project_id)
                if isinstance(entry, dict):
                    project_name = entry.get("name")
                if project_name is None:
                    if rest_projects is None:
                        rest_projects = _fetch_project_names(token)
                    project_name = rest_projects.get(project_id)
            item_object = raw.get("item_object") or {}
            items.append(
                {
                    "content": raw.get("content") or "",
                    "completed_at": raw.get("completed_at"),
                    "project": project_name,
                    "labels": list(item_object.get("labels") or raw.get("labels") or []),
                }
            )
        if len(page) < COMPLETED_PAGE_LIMIT:
            break
        offset += len(page)
    return items


def fetch_today_tasks(token: Optional[str] = None) -> List[Dict[str, Any]]:
    """Active tasks due today (REST v2 ``/tasks?filter=today``) — load context.

    Returns ``[{"content", "due", "project", "labels", "priority"}, ...]``.
    """
    token = token or load_todoist_token()
    tasks = _http_get_json(TODOIST_REST_API + "/tasks", token, query={"filter": "today"})
    if not isinstance(tasks, list):
        raise TodoistError("Todoist /tasks returned a non-list payload")
    projects: Optional[Dict[str, str]] = None
    normalized: List[Dict[str, Any]] = []
    for raw in tasks:
        project_id = str(raw.get("project_id") or "")
        project_name = None
        if project_id:
            if projects is None:
                projects = _fetch_project_names(token)
            project_name = projects.get(project_id)
        due = raw.get("due") or {}
        normalized.append(
            {
                "content": raw.get("content") or "",
                "due": due.get("date"),
                "project": project_name,
                "labels": list(raw.get("labels") or []),
                "priority": raw.get("priority"),
            }
        )
    return normalized


def health_candidates(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter tasks down to health-journal candidates (human reviews them).

    A task qualifies when any word in its content starts with a
    ``HEALTH_KEYWORDS`` stem (RU or EN), or when it carries a ``HEALTH_LABELS``
    label. Keyword hits win over label hits. Returns::

        [{"label_ru": str, "source": "todoist", "original": str,
          "matched_keyword": str, "completed_at": str|None}, ...]
    """
    candidates: List[Dict[str, Any]] = []
    for task in tasks:
        content = str(task.get("content") or "")
        stem = _match_keyword(content)
        if stem is not None:
            label_ru = HEALTH_KEYWORDS[stem]
            matched = stem
        else:
            label = _match_label(task.get("labels") or [])
            if label is None:
                continue
            label_ru = HEALTH_LABELS[label]
            matched = "label:%s" % label
        candidates.append(
            {
                "label_ru": label_ru,
                "source": "todoist",
                "original": content,
                "matched_keyword": matched,
                "completed_at": task.get("completed_at"),
            }
        )
    return candidates


# --------------------------------------------------------------------------- #
# Internals
# --------------------------------------------------------------------------- #


def _match_keyword(content: str) -> Optional[str]:
    words = _WORD_RE.findall(content.lower())
    for word in words:
        for stem in HEALTH_KEYWORDS:
            if word.startswith(stem):
                return stem
    return None


def _match_label(labels: Any) -> Optional[str]:
    for label in labels:
        normalized = str(label).strip().lower()
        if normalized in HEALTH_LABELS:
            return normalized
    return None


def _normalize_date(value: Union[str, _date]) -> str:
    if isinstance(value, _date):
        return value.isoformat()
    text = str(value or "").strip()
    try:
        return _date.fromisoformat(text).isoformat()
    except ValueError:
        raise ValueError("fetch_completed expects an ISO date (YYYY-MM-DD), got %r" % value)


def _fetch_project_names(token: str) -> Dict[str, str]:
    payload = _http_get_json(TODOIST_REST_API + "/projects", token)
    if not isinstance(payload, list):
        raise TodoistError("Todoist /projects returned a non-list payload")
    return {str(item.get("id")): item.get("name") or "" for item in payload}


def _http_get_json(url: str, token: str, query: Optional[Dict[str, Any]] = None) -> Any:
    if query:
        filtered = {key: value for key, value in query.items() if value not in (None, "")}
        if filtered:
            url += "?" + urlencode(filtered)
    request = Request(url, headers={"Authorization": "Bearer %s" % token, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        try:
            detail = exc.read().decode("utf-8", errors="ignore")
        except Exception:
            detail = ""
        raise TodoistError("Todoist GET %s failed: %s %s" % (url.split("?")[0], exc.code, detail[:200]))
    except URLError as exc:
        raise TodoistError("Todoist GET %s failed: %s" % (url.split("?")[0], exc.reason))
