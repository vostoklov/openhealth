"""Tests for the Todoist connector.

No network: ``urlopen`` is replaced by a fake that serves JSON fixtures and
records every requested URL. Fixtures model the public API shapes:
  * Sync v9 ``completed/get_all`` — {"items": [...], "projects": {id: {...}}}
  * REST v2 ``/tasks`` and ``/projects`` — plain JSON arrays.

Run directly:  PYTHONPATH=$PWD python3 tests/test_todoist.py
"""

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from openhealth.connectors import todoist

TOKEN = "test-token-123"


# --------------------------------------------------------------------------- #
# Fake urlopen plumbing
# --------------------------------------------------------------------------- #


class _FakeResponse:
    def __init__(self, payload):
        self._raw = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_urlopen(responses, calls):
    """Serve queued payloads in order; remember full URLs and auth headers."""

    def fake(request, timeout=None):
        calls.append({"url": request.full_url, "auth": request.get_header("Authorization")})
        if not responses:
            raise AssertionError("unexpected extra request: %s" % request.full_url)
        return _FakeResponse(responses.pop(0))

    return fake


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

COMPLETED_PAGE = {
    "items": [
        {
            "content": "Тренировка: ноги",
            "completed_at": "2026-06-10T07:30:00.000000Z",
            "project_id": "2203",
            "item_object": {"labels": ["fitness"]},
        },
        {
            "content": "Оплатить счета",
            "completed_at": "2026-06-10T10:00:00.000000Z",
            "project_id": "2204",
        },
    ],
    "projects": {
        "2203": {"name": "Здоровье"},
        "2204": {"name": "Быт"},
    },
}

REST_PROJECTS = [
    {"id": "2203", "name": "Здоровье"},
    {"id": "2204", "name": "Быт"},
]

REST_TASKS_TODAY = [
    {
        "content": "Вечерняя йога",
        "project_id": "2203",
        "labels": ["health"],
        "priority": 3,
        "due": {"date": "2026-06-10"},
    },
    {
        "content": "Согласовать договор",
        "project_id": "2204",
        "labels": [],
        "priority": 1,
        "due": {"date": "2026-06-10"},
    },
]


# --------------------------------------------------------------------------- #
# Configuration / token discovery
# --------------------------------------------------------------------------- #


class TokenConfigTests(unittest.TestCase):
    def test_without_token_raises_honest_not_configured(self):
        with TemporaryDirectory() as tmp:
            missing = Path(tmp) / "nope" / "todoist.token"
            with patch.dict("os.environ", {}, clear=True):
                with patch.object(todoist, "TODOIST_TOKEN_PATH", missing):
                    with self.assertRaises(todoist.TodoistNotConfigured) as ctx:
                        todoist.fetch_completed("2026-06-10")
        message = str(ctx.exception)
        self.assertIn("Settings", message)
        self.assertIn("Integrations", message)
        self.assertIn("OPENHEALTH_TODOIST_TOKEN", message)

    def test_not_configured_is_a_todoist_error(self):
        self.assertTrue(issubclass(todoist.TodoistNotConfigured, todoist.TodoistError))

    def test_token_from_env(self):
        with patch.dict("os.environ", {"OPENHEALTH_TODOIST_TOKEN": "  env-token "}, clear=True):
            self.assertEqual(todoist.load_todoist_token(), "env-token")

    def test_token_from_file_fallback(self):
        with TemporaryDirectory() as tmp:
            token_path = Path(tmp) / "todoist.token"
            token_path.write_text("file-token\n", encoding="utf-8")
            with patch.dict("os.environ", {}, clear=True):
                with patch.object(todoist, "TODOIST_TOKEN_PATH", token_path):
                    self.assertEqual(todoist.load_todoist_token(), "file-token")


# --------------------------------------------------------------------------- #
# fetch_completed: parsing + pagination
# --------------------------------------------------------------------------- #


class FetchCompletedTests(unittest.TestCase):
    def test_parses_completed_items(self):
        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([COMPLETED_PAGE], calls)):
            items = todoist.fetch_completed("2026-06-10", token=TOKEN)
        self.assertEqual(len(items), 2)
        first = items[0]
        self.assertEqual(first["content"], "Тренировка: ноги")
        self.assertEqual(first["completed_at"], "2026-06-10T07:30:00.000000Z")
        self.assertEqual(first["project"], "Здоровье")
        self.assertEqual(first["labels"], ["fitness"])
        self.assertEqual(items[1]["labels"], [])
        # Projects resolved from the sync payload itself — no extra REST call.
        self.assertEqual(len(calls), 1)
        self.assertIn("sync/v9/completed/get_all", calls[0]["url"])
        self.assertIn("since=2026-06-10T00%3A00%3A00", calls[0]["url"])
        self.assertIn("until=2026-06-10T23%3A59%3A59", calls[0]["url"])
        self.assertIn("annotate_items=true", calls[0]["url"])
        self.assertEqual(calls[0]["auth"], "Bearer %s" % TOKEN)

    def test_paginates_past_the_page_limit(self):
        limit = todoist.COMPLETED_PAGE_LIMIT
        full_page = {
            "items": [
                {"content": "task %d" % i, "completed_at": "2026-06-10T06:00:00Z", "project_id": "2203"}
                for i in range(limit)
            ],
            "projects": {"2203": {"name": "Здоровье"}},
        }
        tail_page = {
            "items": [{"content": "tail", "completed_at": "2026-06-10T23:00:00Z", "project_id": "2203"}],
            "projects": {"2203": {"name": "Здоровье"}},
        }
        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([full_page, tail_page], calls)):
            items = todoist.fetch_completed("2026-06-10", token=TOKEN)
        self.assertEqual(len(items), limit + 1)
        self.assertEqual(len(calls), 2)
        self.assertIn("offset=0", calls[0]["url"])
        self.assertIn("offset=%d" % limit, calls[1]["url"])

    def test_project_name_falls_back_to_rest_projects(self):
        sync_page = {
            "items": [{"content": "Бег 5к", "completed_at": "2026-06-10T07:00:00Z", "project_id": "2203"}],
            # no "projects" map in the sync payload
        }
        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([sync_page, REST_PROJECTS], calls)):
            items = todoist.fetch_completed("2026-06-10", token=TOKEN)
        self.assertEqual(items[0]["project"], "Здоровье")
        self.assertEqual(len(calls), 2)
        self.assertIn("rest/v2/projects", calls[1]["url"])

    def test_accepts_date_object_and_rejects_garbage(self):
        from datetime import date

        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([{"items": []}], calls)):
            self.assertEqual(todoist.fetch_completed(date(2026, 6, 10), token=TOKEN), [])
        self.assertIn("since=2026-06-10", calls[0]["url"])
        with self.assertRaises(ValueError):
            todoist.fetch_completed("next tuesday", token=TOKEN)

    def test_http_error_becomes_todoist_error(self):
        import io
        from urllib.error import HTTPError

        def boom(request, timeout=None):
            raise HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"error":"no"}'))

        with patch.object(todoist, "urlopen", boom):
            with self.assertRaises(todoist.TodoistError) as ctx:
                todoist.fetch_completed("2026-06-10", token=TOKEN)
        self.assertIn("403", str(ctx.exception))


# --------------------------------------------------------------------------- #
# fetch_today_tasks
# --------------------------------------------------------------------------- #


class FetchTodayTasksTests(unittest.TestCase):
    def test_parses_today_tasks(self):
        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([REST_TASKS_TODAY, REST_PROJECTS], calls)):
            tasks = todoist.fetch_today_tasks(token=TOKEN)
        self.assertEqual(len(tasks), 2)
        self.assertEqual(
            tasks[0],
            {
                "content": "Вечерняя йога",
                "due": "2026-06-10",
                "project": "Здоровье",
                "labels": ["health"],
                "priority": 3,
            },
        )
        self.assertIn("rest/v2/tasks", calls[0]["url"])
        self.assertIn("filter=today", calls[0]["url"])

    def test_empty_list_makes_no_projects_call(self):
        calls = []
        with patch.object(todoist, "urlopen", _fake_urlopen([[]], calls)):
            self.assertEqual(todoist.fetch_today_tasks(token=TOKEN), [])
        self.assertEqual(len(calls), 1)


# --------------------------------------------------------------------------- #
# health_candidates: RU + EN keywords, labels, non-matches
# --------------------------------------------------------------------------- #


class HealthCandidatesTests(unittest.TestCase):
    def test_russian_keyword_match(self):
        out = todoist.health_candidates(
            [{"content": "Тренировка: ноги", "labels": [], "completed_at": "2026-06-10T07:30:00Z"}]
        )
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label_ru"], "тренировка")
        self.assertEqual(out[0]["source"], "todoist")
        self.assertEqual(out[0]["original"], "Тренировка: ноги")
        self.assertEqual(out[0]["matched_keyword"], "тренир")
        self.assertEqual(out[0]["completed_at"], "2026-06-10T07:30:00Z")

    def test_english_keyword_match(self):
        out = todoist.health_candidates([{"content": "Morning run 5k", "labels": []}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label_ru"], "бег")
        self.assertEqual(out[0]["matched_keyword"], "run")

    def test_label_match_without_keyword(self):
        out = todoist.health_candidates([{"content": "Вечерний план", "labels": ["Health"]}])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label_ru"], "здоровье")
        self.assertEqual(out[0]["matched_keyword"], "label:health")

    def test_fitness_label(self):
        out = todoist.health_candidates([{"content": "Сходить на занятие", "labels": ["fitness"]}])
        self.assertEqual(out[0]["label_ru"], "фитнес")
        self.assertEqual(out[0]["matched_keyword"], "label:fitness")

    def test_keyword_wins_over_label(self):
        out = todoist.health_candidates([{"content": "Йога вечером", "labels": ["health"]}])
        self.assertEqual(out[0]["label_ru"], "йога")
        self.assertEqual(out[0]["matched_keyword"], "йог")

    def test_non_health_tasks_are_excluded(self):
        out = todoist.health_candidates(
            [
                {"content": "Купить молоко", "labels": []},
                {"content": "Согласовать договор", "labels": ["work"]},
                {"content": "", "labels": []},
            ]
        )
        self.assertEqual(out, [])

    def test_word_prefix_not_substring(self):
        # "сон" must not fire inside "сезон"/"персональный"; "зал" not inside "вокзала".
        out = todoist.health_candidates(
            [
                {"content": "Сезонная распродажа", "labels": []},
                {"content": "Персональный отчёт", "labels": []},
                {"content": "Встретить у вокзала", "labels": []},
            ]
        )
        self.assertEqual(out, [])

    def test_word_prefix_matches_inflections(self):
        out = todoist.health_candidates(
            [
                {"content": "Записаться к врачу", "labels": []},
                {"content": "Сдать анализы крови", "labels": []},
                {"content": "Прогуляться в парке", "labels": []},
            ]
        )
        self.assertEqual([c["label_ru"] for c in out], ["врач", "анализы", "прогулка"])

    def test_missing_labels_key_is_fine(self):
        out = todoist.health_candidates([{"content": "Meditate 10 min"}])
        self.assertEqual(out[0]["label_ru"], "медитация")

    def test_keyword_dictionary_is_extensible_constant(self):
        self.assertIsInstance(todoist.HEALTH_KEYWORDS, dict)
        for stem in ("тренир", "медит", "walk", "gym", "sleep"):
            self.assertIn(stem, todoist.HEALTH_KEYWORDS)


if __name__ == "__main__":
    unittest.main()
