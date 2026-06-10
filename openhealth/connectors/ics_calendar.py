"""ICS calendar connector — subscription URL -> events -> day load. Pure stdlib.

The lowest-friction calendar path: every major calendar can expose a private
read-only ICS feed (Google: "Secret address in iCal format", Apple/Outlook:
public/secret ICS link). The user pastes the URL once; we fetch and parse it
locally. No OAuth, no API keys, no SDK. The OAuth-based Google sync lives in
``google_calendar.py`` and stays the advanced path.

Contract:
    fetch_ics(url)   -> raw ICS text (8s timeout, capped size)
    parse_ics(text)  -> {"events": [Event...], "warnings": [str...]}
                        Event = {"start_iso", "end_iso", "summary", "all_day"}
    day_load(events, "YYYY-MM-DD") -> day aggregate for the dashboard / agents

RFC 5545 coverage (MVP, honest about the rest):
    - VEVENT with DTSTART/DTEND/SUMMARY/STATUS, line unfolding, text escapes;
    - all-day events (VALUE=DATE, DTEND exclusive per RFC);
    - timezones: ``...Z`` -> UTC; ``TZID=...`` via zoneinfo when available
      (py3.9+), otherwise *assumed local* with an explicit warning; floating
      times are treated as local time;
    - RRULE: only FREQ=DAILY / FREQ=WEEKLY (INTERVAL, COUNT, UNTIL, BYDAY)
      expanded, and only inside a +-RRULE_WINDOW_DAYS window around "now";
      other frequencies keep the base instance and emit ``recurring_skipped``;
    - EXDATE: occurrences on excluded local dates are dropped;
    - RECURRENCE-ID overrides: the override instance is kept as a normal
      event and the matching generated occurrence is skipped (minute match).

All output datetimes are LOCAL-time ISO strings (with UTC offset for timed
events). All-day events use plain dates and an exclusive end date.

PRIVACY: the ICS URL is a secret (it grants read access to the calendar).
It is stored only in ``~/.openhealth/calendar.json`` (0600) and must never be
logged or echoed back by APIs; error messages here never contain the URL.
"""

from __future__ import annotations

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit, urlunsplit
from urllib.request import Request, urlopen

try:  # py3.9+; on older runtimes TZID falls back to local time with a warning
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover - depends on the running interpreter
    ZoneInfo = None

CONFIG_FILE = "calendar.json"
FETCH_TIMEOUT_S = 8
MAX_ICS_BYTES = 20 * 1024 * 1024  # a year of a busy calendar is ~1-2 MB
MAX_URL_LEN = 2000

RRULE_WINDOW_DAYS = 7  # expand recurrences only +-7 days around "now"
MAX_OCCURRENCE_SCAN = 5000  # iteration cap when walking from an old DTSTART

# day_load_score weights (transparent formula, see day_load docstring)
WORKDAY_HOURS = 8.0  # busy-hours normalizer: 8h of meetings -> full 70 points
MEETINGS_NORM = 8  # meetings normalizer: 8 meetings -> full 20 points
GAP_MIN_MINUTES = 60  # a "recovery window" is a gap of at least 1 hour

MAX_DAY_EVENTS = 10  # events echoed back per day
MAX_DAY_GAPS = 5
MAX_DAY_ALL_DAY = 5

_WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
_DT_BASIC_RE = re.compile(r"^(\d{8})(?:T(\d{2})(\d{2})(\d{2})(Z?))?$")


class IcsCalendarError(RuntimeError):
    """Raised on fetch/config problems. Messages never contain the ICS URL."""


# --- config: ~/.openhealth/calendar.json -------------------------------------


def config_home() -> Path:
    """~/.openhealth, overridable via OPENHEALTH_HOME (tests, portable setups)."""
    return Path(os.environ.get("OPENHEALTH_HOME") or "~/.openhealth").expanduser()


def calendar_config_path() -> Path:
    return config_home() / CONFIG_FILE


def load_calendar_config() -> "dict | None":
    """{"ics_url": ..., "enabled": bool} or None if absent/unreadable."""
    path = calendar_config_path()
    if not path.is_file():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("ics_url"), str):
        return None
    return {"ics_url": raw["ics_url"], "enabled": bool(raw.get("enabled", True))}


def save_calendar_config(ics_url: str, enabled: bool = True) -> Path:
    """Validate and persist the ICS URL privately (dir 0700, file 0600)."""
    url = validate_ics_url(ics_url)
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass
    path = calendar_config_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"ics_url": url, "enabled": bool(enabled)}, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def disable_calendar_config() -> bool:
    """Set enabled=false keeping the URL (cheap re-enable). False if no config."""
    config = load_calendar_config()
    if config is None:
        return False
    save_calendar_config(config["ics_url"], enabled=False)
    return True


def validate_ics_url(raw) -> str:
    """Normalize and validate an ICS subscription URL; raises IcsCalendarError.

    Accepts https:// (and webcal://, rewritten to https) URLs that look like a
    calendar feed: path ends with .ics, or a known calendar host
    (calendar.google.com, *.icloud.com), or an /ical/ path segment.
    """
    if not isinstance(raw, str):
        raise IcsCalendarError("ics_url must be a string")
    url = raw.strip()
    if not url or len(url) > MAX_URL_LEN or any(c.isspace() for c in url):
        raise IcsCalendarError("ics_url is empty, too long or contains whitespace")
    if url.lower().startswith("webcal://"):
        url = "https://" + url[len("webcal://"):]
    parts = urlsplit(url)
    if parts.scheme != "https":
        raise IcsCalendarError("only https:// (or webcal://) calendar URLs are accepted")
    host = (parts.hostname or "").lower()
    if not host:
        raise IcsCalendarError("ics_url has no host")
    path = parts.path.lower()
    looks_like_feed = (
        path.endswith(".ics")
        or host == "calendar.google.com"
        or host.endswith(".icloud.com")
        or "/ical/" in path
    )
    if not looks_like_feed:
        raise IcsCalendarError(
            "URL does not look like a calendar feed (expected a .ics link, "
            "calendar.google.com or an iCloud calendar URL)"
        )
    return urlunsplit(parts)


# --- fetch --------------------------------------------------------------------


def fetch_ics(url: str, timeout: float = FETCH_TIMEOUT_S) -> str:
    """Download the ICS feed. Raises IcsCalendarError (without the URL) on failure."""
    request = Request(url, headers={"User-Agent": "OpenHealth/0.1 (+local-first)", "Accept": "text/calendar, */*"})
    try:
        with urlopen(request, timeout=timeout) as response:
            body = response.read(MAX_ICS_BYTES + 1)
    except HTTPError as exc:
        raise IcsCalendarError("calendar feed returned HTTP {}".format(exc.code))
    except URLError as exc:
        raise IcsCalendarError("network error fetching calendar feed: {}".format(getattr(exc, "reason", exc)))
    except OSError as exc:  # timeouts surface as socket errors on some runtimes
        raise IcsCalendarError("network error fetching calendar feed: {}".format(exc.__class__.__name__))
    if len(body) > MAX_ICS_BYTES:
        raise IcsCalendarError("calendar feed is larger than {} MB".format(MAX_ICS_BYTES // (1024 * 1024)))
    return body.decode("utf-8", errors="replace")


# --- ICS parsing --------------------------------------------------------------


def _local_tz():
    return datetime.now().astimezone().tzinfo


def _unfold(text: str):
    """RFC 5545 line unfolding: a line starting with SPACE/TAB continues the previous."""
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return lines


def _unescape(value: str) -> str:
    out = []
    i = 0
    while i < len(value):
        ch = value[i]
        if ch == "\\" and i + 1 < len(value):
            nxt = value[i + 1]
            if nxt in ("n", "N"):
                out.append(" ")
            elif nxt in ("\\", ",", ";"):
                out.append(nxt)
            else:
                out.append(nxt)
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def _split_prop(line: str):
    """'DTSTART;TZID=X:2026...' -> ('DTSTART', {'TZID': 'X'}, '2026...') or None."""
    head, sep, value = line.partition(":")
    if not sep:
        return None
    pieces = head.split(";")
    name = pieces[0].strip().upper()
    params = {}
    for piece in pieces[1:]:
        key, eq, val = piece.partition("=")
        if eq:
            params[key.strip().upper()] = val.strip().strip('"')
    return name, params, value


def _tz_for(tzid: str, warnings: list):
    if ZoneInfo is not None:
        try:
            return ZoneInfo(tzid)
        except Exception:  # noqa: BLE001 - unknown TZID, fall through to local
            pass
    note = "tz_fallback_local: TZID '{}' not resolved, times assumed local".format(tzid)
    if note not in warnings:
        warnings.append(note)
    return _local_tz()


def _parse_dt(value: str, params: dict, warnings: list):
    """ICS date/date-time -> (aware datetime | date, all_day). None if unparsable.

    Z -> UTC; TZID -> zoneinfo or local fallback; floating -> local time.
    """
    value = value.strip()
    match = _DT_BASIC_RE.match(value)
    if not match:
        return None, False
    day_part, hh, mm, ss, zulu = match.groups()
    try:
        base_date = datetime.strptime(day_part, "%Y%m%d").date()
    except ValueError:
        return None, False
    if hh is None or params.get("VALUE") == "DATE":
        return base_date, True
    naive = datetime(base_date.year, base_date.month, base_date.day, int(hh), int(mm), int(ss))
    if zulu:
        return naive.replace(tzinfo=timezone.utc), False
    tzid = params.get("TZID")
    if tzid:
        return naive.replace(tzinfo=_tz_for(tzid, warnings)), False
    return naive.astimezone(), False  # floating time -> local


def _event_dict(start, end, summary: str, all_day: bool) -> dict:
    if all_day:
        start_d = start if isinstance(start, date) and not isinstance(start, datetime) else start.date()
        if end is None:
            end_d = start_d + timedelta(days=1)
        else:
            end_d = end if isinstance(end, date) and not isinstance(end, datetime) else end.date()
            if end_d <= start_d:
                end_d = start_d + timedelta(days=1)
        return {"start_iso": start_d.isoformat(), "end_iso": end_d.isoformat(), "summary": summary, "all_day": True}
    start_local = start.astimezone()
    end_local = (end or start).astimezone()
    if end_local < start_local:
        end_local = start_local
    return {
        "start_iso": start_local.isoformat(),
        "end_iso": end_local.isoformat(),
        "summary": summary,
        "all_day": False,
    }


def _parse_rrule(value: str) -> dict:
    rule = {}
    for piece in value.split(";"):
        key, eq, val = piece.partition("=")
        if eq:
            rule[key.strip().upper()] = val.strip()
    return rule


def _occurrence_skip_keys(start) -> set:
    """Keys an EXDATE/override can match this occurrence by: exact minute + date."""
    if isinstance(start, datetime):
        local = start.astimezone()
        return {local.strftime("%Y-%m-%dT%H:%M"), local.date().isoformat()}
    return {start.isoformat()}


def _expand_rrule(component: dict, window_start, window_end, warnings: list):
    """FREQ=DAILY/WEEKLY occurrences inside the window. Returns list of events.

    COUNT is honored by enumerating occurrences from DTSTART (capped at
    MAX_OCCURRENCE_SCAN candidate steps with an explicit warning on overflow).
    """
    rule = component["rrule"]
    freq = rule.get("FREQ", "").upper()
    start = component["start"]
    all_day = component["all_day"]
    summary = component["summary"]
    duration = component["duration"]
    skip_keys = component["skip_keys"]

    try:
        interval = max(int(rule.get("INTERVAL", "1")), 1)
    except ValueError:
        interval = 1
    count = None
    if "COUNT" in rule:
        try:
            count = max(int(rule["COUNT"]), 0)
        except ValueError:
            count = None
    until, _ = _parse_dt(rule["UNTIL"], {}, warnings) if "UNTIL" in rule else (None, False)

    if isinstance(start, datetime):
        start_local = start.astimezone()
        step_day = timedelta(days=1)
    else:
        start_local = start
        step_day = timedelta(days=1)

    def in_window(candidate) -> bool:
        cand_date = candidate.date() if isinstance(candidate, datetime) else candidate
        return window_start <= cand_date <= window_end

    def past_until(candidate) -> bool:
        if until is None:
            return False
        cand = candidate
        if isinstance(until, datetime) and isinstance(cand, datetime):
            return cand.astimezone() > until.astimezone()
        cand_date = cand.date() if isinstance(cand, datetime) else cand
        until_date = until.date() if isinstance(until, datetime) else until
        return cand_date > until_date

    # candidate generator: chronological occurrence starts from DTSTART
    def daily_candidates():
        k = 0
        while True:
            yield start_local + step_day * interval * k
            k += 1

    def weekly_candidates():
        bydays = []
        for token in (rule.get("BYDAY") or "").split(","):
            token = token.strip().upper()[-2:]  # MVP: ignore ordinal prefixes like 2MO
            if token in _WEEKDAYS:
                bydays.append(_WEEKDAYS[token])
        if not bydays:
            bydays = [start_local.weekday()]
        bydays = sorted(set(bydays))
        week_anchor = start_local - step_day * start_local.weekday()  # Monday of DTSTART week (WKST=MO)
        k = 0
        while True:
            base = week_anchor + step_day * 7 * interval * k
            for wd in bydays:
                candidate = base + step_day * wd
                if candidate >= start_local:
                    yield candidate
            k += 1

    if freq == "DAILY":
        candidates = daily_candidates()
    elif freq == "WEEKLY":
        candidates = weekly_candidates()
    else:
        warnings.append("recurring_skipped: FREQ={} not expanded ('{}')".format(freq or "?", summary[:60]))
        if in_window(start_local):
            return [_event_dict(start, component["end"], summary, all_day)]
        return []

    events = []
    produced = 0
    for steps, candidate in enumerate(candidates):
        if steps >= MAX_OCCURRENCE_SCAN:
            warnings.append("rrule_scan_capped: stopped expanding '{}'".format(summary[:60]))
            break
        if count is not None and produced >= count:
            break
        if past_until(candidate):
            break
        cand_date = candidate.date() if isinstance(candidate, datetime) else candidate
        if cand_date > window_end:
            break
        produced += 1  # occurrence exists even if it is before the window (COUNT semantics)
        if not in_window(candidate):
            continue
        if _occurrence_skip_keys(candidate) & skip_keys:
            continue
        end = candidate + duration if duration is not None else None
        events.append(_event_dict(candidate, end, summary, all_day))
    return events


def parse_ics(text: str, now: "datetime | None" = None, window_days: int = RRULE_WINDOW_DAYS) -> dict:
    """Parse ICS text -> {"events": [...], "warnings": [...]}, sorted by start.

    ``now`` (aware datetime) anchors the RRULE expansion window; defaults to
    the current local time. Non-recurring events are returned regardless of
    the window — day_load() filters by date.
    """
    warnings: list = []
    if now is None:
        now = datetime.now().astimezone()
    window_start = (now - timedelta(days=window_days)).date()
    window_end = (now + timedelta(days=window_days)).date()

    components = []
    current = None
    for line in _unfold(text):
        prop = _split_prop(line)
        if prop is None:
            continue
        name, params, value = prop
        if name == "BEGIN" and value.strip().upper() == "VEVENT":
            current = {"params": {}, "exdates": set()}
            continue
        if name == "END" and value.strip().upper() == "VEVENT":
            if current is not None:
                components.append(current)
            current = None
            continue
        if current is None:
            continue
        if name == "DTSTART":
            current["dtstart"] = (value, params)
        elif name == "DTEND":
            current["dtend"] = (value, params)
        elif name == "SUMMARY":
            current["summary"] = _unescape(value).strip()
        elif name == "STATUS":
            current["status"] = value.strip().upper()
        elif name == "RRULE":
            current["rrule"] = _parse_rrule(value)
        elif name == "UID":
            current["uid"] = value.strip()
        elif name == "RECURRENCE-ID":
            current["recurrence_id"] = (value, params)
        elif name == "EXDATE":
            for piece in value.split(","):
                parsed, _ = _parse_dt(piece, params, warnings)
                if parsed is not None:
                    current["exdates"] |= _occurrence_skip_keys(
                        parsed.astimezone() if isinstance(parsed, datetime) else parsed
                    )

    if not components and "BEGIN:VCALENDAR" not in text.upper():
        warnings.append("not_ics: no VEVENT/VCALENDAR found in feed")

    # First pass: overrides (RECURRENCE-ID) claim their original occurrence slots.
    overrides_by_uid: dict = {}
    for component in components:
        if "recurrence_id" in component and component.get("uid"):
            value, params = component["recurrence_id"]
            parsed, _ = _parse_dt(value, params, warnings)
            if parsed is not None:
                keys = _occurrence_skip_keys(parsed.astimezone() if isinstance(parsed, datetime) else parsed)
                overrides_by_uid.setdefault(component["uid"], set()).update(keys)

    events = []
    for component in components:
        if component.get("status") == "CANCELLED":
            continue
        if "dtstart" not in component:
            warnings.append("event_skipped: VEVENT without DTSTART")
            continue
        value, params = component["dtstart"]
        start, all_day = _parse_dt(value, params, warnings)
        if start is None:
            warnings.append("event_skipped: unparsable DTSTART '{}'".format(value[:32]))
            continue
        end = None
        if "dtend" in component:
            end_value, end_params = component["dtend"]
            end, _ = _parse_dt(end_value, end_params, warnings)
        summary = component.get("summary") or "(no title)"

        if "rrule" in component:
            duration = None
            if end is not None and isinstance(start, datetime) and isinstance(end, datetime):
                duration = end - start
            elif end is not None and all_day:
                duration = end - start
            skip_keys = set(component["exdates"])
            if component.get("uid") in overrides_by_uid and "recurrence_id" not in component:
                skip_keys |= overrides_by_uid[component["uid"]]
            events.extend(
                _expand_rrule(
                    {
                        "rrule": component["rrule"],
                        "start": start,
                        "end": end,
                        "duration": duration,
                        "all_day": all_day,
                        "summary": summary,
                        "skip_keys": skip_keys,
                    },
                    window_start,
                    window_end,
                    warnings,
                )
            )
        else:
            events.append(_event_dict(start, end, summary, all_day))

    events.sort(key=lambda e: e["start_iso"])
    return {"events": events, "warnings": warnings}


# --- day aggregate -------------------------------------------------------------


def _as_local_dt(iso: str) -> datetime:
    parsed = datetime.fromisoformat(iso)
    if parsed.tzinfo is None:
        return parsed.astimezone()  # naive -> assume local
    return parsed.astimezone()


def day_load(events, day: str) -> dict:
    """Aggregate one local day for the "day pulse" view.

    day_load_score (0-100), transparent formula:
        70 * min(busy_hours / 8, 1)            — meeting hours vs an 8h workday
      + 20 * min(meetings_count / 8, 1)        — context switches
      + 10 if meetings_count >= 3 and there is no gap >= 1h (no recovery window)
    Overlapping meetings are merged before counting busy hours, so double-booked
    slots are not double-counted. All-day events are listed separately and do
    not add busy hours.
    """
    day_start = _as_local_dt(day + "T00:00:00")
    day_end = day_start + timedelta(days=1)

    timed = []
    all_day_titles = []
    for event in events:
        if event.get("all_day"):
            if event["start_iso"] <= day < event["end_iso"]:
                all_day_titles.append(event.get("summary") or "(no title)")
            continue
        try:
            start = _as_local_dt(event["start_iso"])
            end = _as_local_dt(event["end_iso"])
        except (KeyError, ValueError):
            continue
        clip_start = max(start, day_start)
        clip_end = min(end, day_end)
        if clip_end <= clip_start:
            continue
        timed.append({"start": clip_start, "end": clip_end, "summary": event.get("summary") or "(no title)"})

    timed.sort(key=lambda item: item["start"])

    merged = []  # merged busy intervals
    for item in timed:
        if merged and item["start"] <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], item["end"])
        else:
            merged.append([item["start"], item["end"]])

    busy_minutes = sum(int((end - start).total_seconds() // 60) for start, end in merged)
    busy_hours = round(busy_minutes / 60.0, 1)
    meetings_count = len(timed)

    gaps = []
    for (_, prev_end), (next_start, _) in zip(merged, merged[1:]):
        if (next_start - prev_end).total_seconds() >= GAP_MIN_MINUTES * 60:
            gaps.append({"start": prev_end.strftime("%H:%M"), "end": next_start.strftime("%H:%M")})

    hours_part = round(70 * min(busy_minutes / 60.0 / WORKDAY_HOURS, 1.0))
    meetings_part = round(20 * min(meetings_count / float(MEETINGS_NORM), 1.0))
    fragmentation_part = 10 if (meetings_count >= 3 and not gaps) else 0
    score = min(hours_part + meetings_part + fragmentation_part, 100)

    return {
        "date": day,
        "meetings_count": meetings_count,
        "busy_hours": busy_hours,
        "first_event": merged[0][0].strftime("%H:%M") if merged else None,
        "last_event": merged[-1][1].strftime("%H:%M") if merged else None,
        "gaps_over_1h": len(gaps),
        "gaps": gaps[:MAX_DAY_GAPS],
        "day_load_score": score,
        "score_parts": {
            "busy_hours": hours_part,
            "meetings": meetings_part,
            "no_recovery_gap": fragmentation_part,
        },
        "all_day_count": len(all_day_titles),
        "all_day": all_day_titles[:MAX_DAY_ALL_DAY],
        "events": [
            {
                "start": item["start"].strftime("%H:%M"),
                "end": item["end"].strftime("%H:%M"),
                "summary": item["summary"],
            }
            for item in timed[:MAX_DAY_EVENTS]
        ],
    }
