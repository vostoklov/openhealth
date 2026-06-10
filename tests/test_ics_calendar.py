"""Tests for the ICS calendar connector and the /api/calendar bridge endpoints.

No network anywhere: ``fetch_ics`` / ``urlopen`` are mocked. The bridge module
is loaded by path because ui/web is not a package. Timezone-sensitive asserts
compare through UTC so they pass on any machine timezone.
"""

import importlib.util
import stat
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

from openhealth.connectors import ics_calendar

_SERVER_PATH = Path(__file__).resolve().parent.parent / "ui" / "web" / "server.py"
_spec = importlib.util.spec_from_file_location("bridge_server_for_calendar", _SERVER_PATH)
server = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(server)

NOW = datetime(2026, 6, 10, 12, 0, tzinfo=timezone.utc)  # anchors RRULE windows


@pytest.fixture(autouse=True)
def oh_home(tmp_path, monkeypatch):
    """Isolate every test from the real ~/.openhealth; reset the bridge cache."""
    home = tmp_path / "oh-home"
    monkeypatch.setenv("OPENHEALTH_HOME", str(home))
    server.invalidate_calendar_cache()
    return home


def ics(*vevents):
    return "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(vevents) + "END:VCALENDAR\r\n"


def vevent(body):
    return "BEGIN:VEVENT\r\n" + body.strip() + "\r\nEND:VEVENT\r\n"


def _utc(iso):
    return datetime.fromisoformat(iso).astimezone(timezone.utc)


# --- parse_ics: basics --------------------------------------------------------


def test_parse_simple_timed_event_utc():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260610T070000Z\r\nDTEND:20260610T080000Z\r\nSUMMARY:Standup"))
    )
    assert parsed["warnings"] == []
    (event,) = parsed["events"]
    assert event["summary"] == "Standup"
    assert event["all_day"] is False
    assert _utc(event["start_iso"]) == datetime(2026, 6, 10, 7, 0, tzinfo=timezone.utc)
    assert _utc(event["end_iso"]) == datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)


def test_parse_all_day_event_exclusive_end():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART;VALUE=DATE:20260610\r\nDTEND;VALUE=DATE:20260612\r\nSUMMARY:Conference"))
    )
    (event,) = parsed["events"]
    assert event == {"start_iso": "2026-06-10", "end_iso": "2026-06-12", "summary": "Conference", "all_day": True}


def test_parse_all_day_without_dtend_lasts_one_day():
    parsed = ics_calendar.parse_ics(ics(vevent("DTSTART;VALUE=DATE:20260610\r\nSUMMARY:Birthday")))
    (event,) = parsed["events"]
    assert (event["start_iso"], event["end_iso"]) == ("2026-06-10", "2026-06-11")


def test_parse_tzid_resolves_or_warns_honestly():
    parsed = ics_calendar.parse_ics(
        ics(
            vevent(
                "DTSTART;TZID=Europe/Moscow:20260610T090000\r\n"
                "DTEND;TZID=Europe/Moscow:20260610T100000\r\nSUMMARY:Call"
            )
        )
    )
    (event,) = parsed["events"]
    if ics_calendar.ZoneInfo is not None:
        assert _utc(event["start_iso"]) == datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)  # MSK = UTC+3
        assert parsed["warnings"] == []
    else:  # py3.8 runtime: assumed local, explicitly flagged
        assert any(w.startswith("tz_fallback_local") for w in parsed["warnings"])


def test_parse_tzid_fallback_is_flagged_when_zoneinfo_missing(monkeypatch):
    monkeypatch.setattr(ics_calendar, "ZoneInfo", None)
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART;TZID=Europe/Moscow:20260610T090000\r\nSUMMARY:Call"))
    )
    assert len(parsed["events"]) == 1
    assert any(w.startswith("tz_fallback_local") and "Europe/Moscow" in w for w in parsed["warnings"])


def test_parse_folded_line_and_escaped_summary():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260610T070000Z\r\nSUMMARY:Plan\\, sync abou\r\n t the launch"))
    )
    assert parsed["events"][0]["summary"] == "Plan, sync about the launch"


def test_parse_skips_cancelled_and_dtstart_less_events():
    parsed = ics_calendar.parse_ics(
        ics(
            vevent("DTSTART:20260610T070000Z\r\nSUMMARY:Gone\r\nSTATUS:CANCELLED"),
            vevent("SUMMARY:No start"),
        )
    )
    assert parsed["events"] == []
    assert any(w.startswith("event_skipped") for w in parsed["warnings"])


def test_parse_garbage_is_honest_not_crashy():
    parsed = ics_calendar.parse_ics("hello, this is not a calendar at all")
    assert parsed["events"] == []
    assert any(w.startswith("not_ics") for w in parsed["warnings"])


# --- parse_ics: recurrence ----------------------------------------------------


def test_rrule_daily_count_expands_inside_window():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260608T090000Z\r\nDTEND:20260608T093000Z\r\nSUMMARY:Daily\r\nRRULE:FREQ=DAILY;COUNT=5")),
        now=NOW,
    )
    starts = [_utc(e["start_iso"]) for e in parsed["events"]]
    assert starts == [datetime(2026, 6, 8 + k, 9, 0, tzinfo=timezone.utc) for k in range(5)]
    assert all(_utc(e["end_iso"]) - _utc(e["start_iso"]) == ics_calendar.timedelta(minutes=30)
               for e in parsed["events"])


def test_rrule_weekly_byday_expands_only_window():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260601T100000Z\r\nDTEND:20260601T110000Z\r\nSUMMARY:Gym\r\nRRULE:FREQ=WEEKLY;BYDAY=MO,WE")),
        now=NOW,  # window 2026-06-03 .. 2026-06-17
    )
    days = [_utc(e["start_iso"]).date().isoformat() for e in parsed["events"]]
    assert days == ["2026-06-03", "2026-06-08", "2026-06-10", "2026-06-15", "2026-06-17"]


def test_rrule_until_stops_expansion():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260608T090000Z\r\nSUMMARY:Short\r\nRRULE:FREQ=DAILY;UNTIL=20260610T090000Z")),
        now=NOW,
    )
    days = [_utc(e["start_iso"]).date().isoformat() for e in parsed["events"]]
    assert days == ["2026-06-08", "2026-06-09", "2026-06-10"]


def test_rrule_exdate_drops_occurrence_but_counts_it():
    parsed = ics_calendar.parse_ics(
        ics(
            vevent(
                "DTSTART:20260609T090000Z\r\nSUMMARY:Sync\r\n"
                "RRULE:FREQ=DAILY;COUNT=3\r\nEXDATE:20260610T090000Z"
            )
        ),
        now=NOW,
    )
    days = [_utc(e["start_iso"]).date().isoformat() for e in parsed["events"]]
    assert days == ["2026-06-09", "2026-06-11"]


def test_rrule_monthly_keeps_base_instance_with_warning():
    parsed = ics_calendar.parse_ics(
        ics(vevent("DTSTART:20260610T090000Z\r\nSUMMARY:Rent\r\nRRULE:FREQ=MONTHLY")),
        now=NOW,
    )
    assert len(parsed["events"]) == 1
    assert any(w.startswith("recurring_skipped") and "MONTHLY" in w for w in parsed["warnings"])


def test_rrule_override_instance_not_duplicated():
    master = vevent(
        "UID:abc\r\nDTSTART:20260609T090000Z\r\nDTEND:20260609T100000Z\r\n"
        "SUMMARY:Sync\r\nRRULE:FREQ=DAILY;COUNT=2"
    )
    override = vevent(
        "UID:abc\r\nRECURRENCE-ID:20260610T090000Z\r\n"
        "DTSTART:20260610T140000Z\r\nDTEND:20260610T150000Z\r\nSUMMARY:Sync (moved)"
    )
    parsed = ics_calendar.parse_ics(ics(master, override), now=NOW)
    summaries = sorted((_utc(e["start_iso"]).isoformat(), e["summary"]) for e in parsed["events"])
    assert summaries == [
        ("2026-06-09T09:00:00+00:00", "Sync"),
        ("2026-06-10T14:00:00+00:00", "Sync (moved)"),
    ]


# --- day_load -----------------------------------------------------------------


def _ev(start, end, summary="x"):
    """Timed event with naive-local ISO (timezone-independent in tests)."""
    return {"start_iso": start, "end_iso": end, "summary": summary, "all_day": False}


def test_day_load_empty_day():
    load = ics_calendar.day_load([], "2026-06-10")
    assert load["meetings_count"] == 0
    assert load["busy_hours"] == 0
    assert load["first_event"] is None and load["last_event"] is None
    assert load["day_load_score"] == 0
    assert load["events"] == [] and load["gaps"] == []


def test_day_load_merges_overlaps_counts_gaps_and_scores():
    events = [
        _ev("2026-06-10T09:00:00", "2026-06-10T10:00:00", "A"),
        _ev("2026-06-10T09:30:00", "2026-06-10T10:30:00", "B"),  # overlap with A
        _ev("2026-06-10T11:00:00", "2026-06-10T12:00:00", "C"),  # 30 min gap (ignored)
        _ev("2026-06-10T14:00:00", "2026-06-10T15:00:00", "D"),  # 2h gap (counted)
        _ev("2026-06-11T09:00:00", "2026-06-11T10:00:00", "other day"),
    ]
    load = ics_calendar.day_load(events, "2026-06-10")
    assert load["meetings_count"] == 4
    assert load["busy_hours"] == 3.5  # 1.5 merged + 1 + 1, no double counting
    assert load["first_event"] == "09:00" and load["last_event"] == "15:00"
    assert load["gaps_over_1h"] == 1
    assert load["gaps"] == [{"start": "12:00", "end": "14:00"}]
    # transparent formula: 70*min(3.5/8,1)=31, 20*min(4/8,1)=10, gap exists -> +0
    assert load["score_parts"] == {"busy_hours": 31, "meetings": 10, "no_recovery_gap": 0}
    assert load["day_load_score"] == 41
    assert [e["summary"] for e in load["events"]] == ["A", "B", "C", "D"]


def test_day_load_back_to_back_day_gets_fragmentation_penalty():
    events = [
        _ev("2026-06-10T09:00:00", "2026-06-10T10:00:00"),
        _ev("2026-06-10T10:00:00", "2026-06-10T11:00:00"),
        _ev("2026-06-10T11:00:00", "2026-06-10T12:00:00"),
    ]
    load = ics_calendar.day_load(events, "2026-06-10")
    # 70*min(3/8,1)=26, 20*min(3/8,1)=8 (round-half-even), 3+ meetings & no 1h gap -> +10
    assert load["score_parts"] == {"busy_hours": 26, "meetings": 8, "no_recovery_gap": 10}
    assert load["day_load_score"] == 44
    assert load["gaps_over_1h"] == 0


def test_day_load_score_saturates_at_100():
    events = [
        _ev("2026-06-10T{:02d}:00:00".format(h), "2026-06-10T{:02d}:00:00".format(h + 1), "m{}".format(h))
        for h in range(8, 17)  # nine 1h meetings back-to-back
    ]
    load = ics_calendar.day_load(events, "2026-06-10")
    assert load["day_load_score"] == 100
    assert load["busy_hours"] == 9.0


def test_day_load_all_day_listed_separately_and_events_capped():
    events = [{"start_iso": "2026-06-10", "end_iso": "2026-06-11", "summary": "Travel", "all_day": True}]
    events += [
        _ev("2026-06-10T{:02d}:00:00".format(8 + k), "2026-06-10T{:02d}:20:00".format(8 + k), "m{}".format(k))
        for k in range(12)
    ]
    load = ics_calendar.day_load(events, "2026-06-10")
    assert load["all_day_count"] == 1 and load["all_day"] == ["Travel"]
    assert load["meetings_count"] == 12
    assert len(load["events"]) == 10  # capped
    assert load["busy_hours"] == 4.0  # all-day adds no busy hours


def test_day_load_clips_event_crossing_midnight():
    events = [_ev("2026-06-09T23:00:00", "2026-06-10T01:00:00", "night")]
    load = ics_calendar.day_load(events, "2026-06-10")
    assert load["meetings_count"] == 1
    assert load["busy_hours"] == 1.0
    assert load["first_event"] == "00:00" and load["last_event"] == "01:00"


# --- config + URL validation --------------------------------------------------


def test_validate_ics_url_accepts_feeds_and_rewrites_webcal():
    google = "https://calendar.google.com/calendar/ical/x%40gmail.com/private-abc123/basic.ics"
    assert ics_calendar.validate_ics_url(google) == google
    assert ics_calendar.validate_ics_url("webcal://p64-caldav.icloud.com/published/2/token").startswith(
        "https://p64-caldav.icloud.com/"
    )
    assert ics_calendar.validate_ics_url(" https://example.com/me/cal.ics ").endswith("/me/cal.ics")


@pytest.mark.parametrize(
    "bad",
    [
        "http://calendar.google.com/calendar/ical/x/private/basic.ics",  # plaintext
        "https://example.com/page.html",  # not a feed
        "ftp://example.com/cal.ics",
        "https://example.com/cal .ics",  # whitespace
        "",
        None,
        123,
    ],
)
def test_validate_ics_url_rejects_non_feeds(bad):
    with pytest.raises(ics_calendar.IcsCalendarError):
        ics_calendar.validate_ics_url(bad)


def test_save_load_disable_config_roundtrip(oh_home):
    assert ics_calendar.load_calendar_config() is None
    path = ics_calendar.save_calendar_config("https://example.com/cal.ics")
    assert path == oh_home / "calendar.json"
    mode = stat.S_IMODE(path.stat().st_mode)
    assert mode == 0o600  # the URL is a secret
    config = ics_calendar.load_calendar_config()
    assert config == {"ics_url": "https://example.com/cal.ics", "enabled": True}
    assert ics_calendar.disable_calendar_config() is True
    config = ics_calendar.load_calendar_config()
    assert config["enabled"] is False and config["ics_url"].endswith("cal.ics")  # URL kept


def test_disable_without_config_is_false():
    assert ics_calendar.disable_calendar_config() is False


# --- fetch_ics (urlopen mocked) -------------------------------------------------


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def read(self, n=-1):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_fetch_ics_returns_text(monkeypatch):
    monkeypatch.setattr(ics_calendar, "urlopen", lambda req, timeout: _FakeResponse(b"BEGIN:VCALENDAR"))
    assert ics_calendar.fetch_ics("https://example.com/cal.ics") == "BEGIN:VCALENDAR"


def test_fetch_ics_errors_never_leak_the_url(monkeypatch):
    secret = "https://calendar.google.com/calendar/ical/me/private-SECRET/basic.ics"

    def boom(req, timeout):
        raise HTTPError(secret, 404, "not found", None, None)

    monkeypatch.setattr(ics_calendar, "urlopen", boom)
    with pytest.raises(ics_calendar.IcsCalendarError) as err:
        ics_calendar.fetch_ics(secret)
    assert "404" in str(err.value) and "SECRET" not in str(err.value)

    def net_down(req, timeout):
        raise URLError("no network")

    monkeypatch.setattr(ics_calendar, "urlopen", net_down)
    with pytest.raises(ics_calendar.IcsCalendarError):
        ics_calendar.fetch_ics(secret)


# --- bridge endpoints (pure handlers, no HTTP) ----------------------------------


def test_api_calendar_get_unconfigured_explains_how():
    status, body = server.handle_calendar_get(None)
    assert status == 200
    assert body["configured"] is False
    assert 2 <= len(body["how"]) <= 3
    assert any("Secret address" in line for line in body["how"])


def test_api_calendar_get_rejects_bad_dates():
    assert server.handle_calendar_get("nope")[0] == 400
    assert server.handle_calendar_get("2026-13-99")[0] == 400


def test_api_calendar_post_get_flow_with_cache(monkeypatch):
    status, body = server.handle_calendar_post({"ics_url": "https://example.com/cal.ics"})
    assert (status, body["status"], body["configured"]) == (200, "ok", True)
    assert "ics_url" not in body  # never echoed back

    calls = {"n": 0}

    def fake_fetch(url, timeout=8):
        calls["n"] += 1
        return ics(vevent("DTSTART:20260610T070000Z\r\nDTEND:20260610T083000Z\r\nSUMMARY:Standup"))

    monkeypatch.setattr(ics_calendar, "fetch_ics", fake_fetch)
    status, body = server.handle_calendar_get("2026-06-10")
    assert status == 200 and body["status"] == "ok" and body["configured"] is True
    assert body["cached"] is False
    assert body["day"]["meetings_count"] == 1
    assert body["day"]["busy_hours"] == 1.5

    status, body = server.handle_calendar_get("2026-06-10")
    assert body["cached"] is True
    assert calls["n"] == 1  # second GET served from the 10-minute cache


def test_api_calendar_post_rejects_bad_payloads():
    assert server.handle_calendar_post({"ics_url": "http://x.ics"})[0] == 400
    assert server.handle_calendar_post(["not", "a", "dict"])[0] == 400
    assert server.handle_calendar_post({})[0] == 400


def test_api_calendar_fetch_error_is_honest(monkeypatch):
    server.handle_calendar_post({"ics_url": "https://example.com/cal.ics"})

    def boom(url, timeout=8):
        raise ics_calendar.IcsCalendarError("calendar feed returned HTTP 403")

    monkeypatch.setattr(ics_calendar, "fetch_ics", boom)
    status, body = server.handle_calendar_get(None)
    assert status == 200
    assert body == {"configured": True, "status": "error", "message": "calendar feed returned HTTP 403"}


def test_api_calendar_delete_disables():
    assert server.handle_calendar_delete()[1]["was_configured"] is False
    server.handle_calendar_post({"ics_url": "https://example.com/cal.ics"})
    status, body = server.handle_calendar_delete()
    assert (status, body["configured"], body["was_configured"]) == (200, False, True)
    status, body = server.handle_calendar_get(None)
    assert body["configured"] is False  # disabled feed behaves as unconfigured
