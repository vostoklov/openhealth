"""Withings direct API connector — scales, BPM cuffs, sleep mat → Observations.

First provider from the providers catalog with a live OAuth2 pull. Clean-room
implementation written from the public developer.withings.com documentation,
pure stdlib, nothing leaves the machine except the Withings API calls.

Withings deviates from textbook OAuth2/REST in three ways this module handles
explicitly (do not "fix" them, they are the documented contract):

  * Every response — including token grants — is wrapped in an envelope
    ``{"status": 0, "body": {...}}``. HTTP status is 200 even on failure;
    real errors live in the ``status`` field (e.g. 401 invalid token).
  * Token refresh is not a standard grant endpoint: it is the same
    ``/v2/oauth2`` call with ``action=requesttoken`` and
    ``grant_type=refresh_token``.
  * Measure values arrive as integer mantissa plus power-of-ten exponent:
    ``real = value * 10 ** unit`` (75.5 kg comes back as value=75500, unit=-3).

Config lives in ``~/.openhealth/withings.json`` (dir 0700, file 0600):
``{"client_id": .., "client_secret": .., "tokens": {"access_token": ..,
"refresh_token": .., "expires_at": <unix>}}``. Missing client credentials
fall back to ``OPENHEALTH_WITHINGS_CLIENT_ID`` / ``OPENHEALTH_WITHINGS_CLIENT_SECRET``.
The access token auto-refreshes (and persists) when within 60 s of expiry.

Entry points:
    auth_url(redirect_uri, state) -> str
    exchange_code(code, redirect_uri) -> dict (tokens, saved to config)
    fetch_measures(start_date, end_date) -> list[dict]      (Observation-shaped)
    fetch_sleep_summary(start_date, end_date) -> list[dict] (Observation-shaped)
    summarize(records) -> dict
"""

import json
import os
from datetime import date as date_class
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

SOURCE = "withings"
SOURCE_ID = "withings"
CONFIG_FILE = "withings.json"

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
SLEEP_URL = "https://wbsapi.withings.net/v2/sleep"

DEFAULT_SCOPE = "user.metrics,user.activity"
ENV_CLIENT_ID = "OPENHEALTH_WITHINGS_CLIENT_ID"
ENV_CLIENT_SECRET = "OPENHEALTH_WITHINGS_CLIENT_SECRET"

# Withings devices measure directly; same grade as raw Oura/WHOOP signals.
CONF_DEVICE = 0.9

# Token refreshed when it expires within this many seconds.
_EXPIRY_SLACK_S = 60

# Withings meastype -> canonical metric. Catalog of the types we ingest;
# anything else in a measuregrp is skipped (goals, unknown future types).
# meastype: (metric_name, unit, observation_kind, domain)
MEASTYPES: Dict[int, Tuple[str, str, str, str]] = {
    1: ("weight_kg", "kg", "weight", "body"),
    6: ("body_fat_pct", "%", "body_composition", "body"),
    76: ("muscle_mass_kg", "kg", "body_composition", "body"),
    88: ("bone_mass_kg", "kg", "body_composition", "body"),
    9: ("bp_diastolic", "mmHg", "blood_pressure", "pulse"),
    10: ("bp_systolic", "mmHg", "blood_pressure", "pulse"),
    11: ("hr_bpm", "bpm", "heart_rate", "pulse"),
}

# Sleep summary fields (seconds in the API) -> canonical metric.
# field: (metric_name, unit, observation_kind, transform)
_SLEEP_FIELDS: Dict[str, Tuple[str, str, str, str]] = {
    "total_sleep_time": ("sleep_duration_h", "h", "sleep_session", "sec_to_h"),
    "deepsleepduration": ("sleep_deep_h", "h", "sleep_session", "sec_to_h"),
    "remsleepduration": ("sleep_rem_h", "h", "sleep_session", "sec_to_h"),
    "lightsleepduration": ("sleep_light_h", "h", "sleep_session", "sec_to_h"),
    "durationtosleep": ("sleep_latency_min", "min", "sleep_session", "sec_to_min"),
    "hr_average": ("sleep_hr_avg_bpm", "bpm", "heart_rate", "ident"),
}
_SLEEP_DATA_FIELDS = ",".join(sorted(_SLEEP_FIELDS))
# When total_sleep_time is absent (older accounts), sum the stages instead.
_SLEEP_STAGE_SECONDS = ("deepsleepduration", "remsleepduration", "lightsleepduration")


class WithingsError(RuntimeError):
    """Raised when Withings configuration or API calls fail."""


class WithingsNotConfigured(WithingsError):
    """Raised when client credentials or tokens are missing."""


# --------------------------------------------------------------------------- #
# Config: ~/.openhealth/withings.json (0600), env fallback for client creds
# --------------------------------------------------------------------------- #


def config_home() -> Path:
    """``~/.openhealth``, overridable via ``OPENHEALTH_HOME`` (tests, portability)."""
    return Path(os.environ.get("OPENHEALTH_HOME") or "~/.openhealth").expanduser()


def withings_config_path() -> Path:
    return config_home() / CONFIG_FILE


def load_config() -> Dict[str, Any]:
    """Config dict from file, with env fallback for missing client credentials.

    Always returns a dict with ``client_id``/``client_secret``/``tokens`` keys
    (possibly None/empty); validation happens at the call sites that need them.
    """
    raw: Dict[str, Any] = {}
    path = withings_config_path()
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise WithingsError("Cannot read %s: %s" % (path, exc)) from None
        if isinstance(loaded, dict):
            raw = loaded
    return {
        "client_id": raw.get("client_id") or os.environ.get(ENV_CLIENT_ID),
        "client_secret": raw.get("client_secret") or os.environ.get(ENV_CLIENT_SECRET),
        "tokens": raw.get("tokens") if isinstance(raw.get("tokens"), dict) else None,
    }


def save_config(config: Dict[str, Any]) -> Path:
    """Persist the config privately (dir 0700, file 0600, atomic replace)."""
    home = config_home()
    home.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(home, 0o700)
    except OSError:
        pass  # exotic FS without chmod — keep going, data still local
    path = withings_config_path()
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return path


def _require_client_credentials(config: Dict[str, Any]) -> Tuple[str, str]:
    client_id = config.get("client_id")
    client_secret = config.get("client_secret")
    if not client_id or not client_secret:
        raise WithingsNotConfigured(
            "Missing Withings client credentials. Put client_id/client_secret into %s "
            "or export %s / %s." % (withings_config_path(), ENV_CLIENT_ID, ENV_CLIENT_SECRET)
        )
    return str(client_id), str(client_secret)


# --------------------------------------------------------------------------- #
# OAuth2: authorize URL, code exchange, non-standard requesttoken refresh
# --------------------------------------------------------------------------- #


def auth_url(redirect_uri: str, state: str, scope: str = DEFAULT_SCOPE) -> str:
    """Authorization URL for the user to open in a browser."""
    client_id, _ = _require_client_credentials(load_config())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "state": state,
        }
    )
    return "%s?%s" % (AUTHORIZE_URL, query)


def exchange_code(code: str, redirect_uri: str) -> Dict[str, Any]:
    """Exchange an OAuth code for tokens and persist them into the config."""
    config = load_config()
    client_id, client_secret = _require_client_credentials(config)
    body = _token_request(
        {
            "action": "requesttoken",
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        }
    )
    return _store_tokens(config, body)


def refresh_tokens(config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Refresh via the non-standard ``action=requesttoken`` + refresh_token grant."""
    config = config if config is not None else load_config()
    client_id, client_secret = _require_client_credentials(config)
    tokens = config.get("tokens") or {}
    refresh_token = tokens.get("refresh_token")
    if not refresh_token:
        raise WithingsNotConfigured(
            "No Withings refresh token stored. Run the OAuth flow (withings-auth-url + withings-exchange-code) first."
        )
    body = _token_request(
        {
            "action": "requesttoken",
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        }
    )
    return _store_tokens(config, body)


def ensure_access_token() -> str:
    """Valid access token, refreshing (and persisting) when close to expiry."""
    config = load_config()
    tokens = config.get("tokens") or {}
    access_token = tokens.get("access_token")
    if not access_token:
        raise WithingsNotConfigured(
            "No Withings tokens stored. Run the OAuth flow (withings-auth-url + withings-exchange-code) first."
        )
    expires_at = tokens.get("expires_at")
    now = int(datetime.now(timezone.utc).timestamp())
    if isinstance(expires_at, (int, float)) and now < int(expires_at) - _EXPIRY_SLACK_S:
        return str(access_token)
    return str(refresh_tokens(config)["access_token"])


def _token_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    return _api_call(TOKEN_URL, payload, access_token=None, context="token request")


def _store_tokens(config: Dict[str, Any], body: Dict[str, Any]) -> Dict[str, Any]:
    if "access_token" not in body:
        raise WithingsError("Withings token response is missing access_token: %s" % sorted(body))
    previous = config.get("tokens") or {}
    expires_in = int(body.get("expires_in", 3 * 3600))
    tokens = {
        "access_token": body["access_token"],
        # Withings rotates refresh tokens; fall back to the previous one if absent.
        "refresh_token": body.get("refresh_token") or previous.get("refresh_token"),
        "expires_at": int(datetime.now(timezone.utc).timestamp()) + expires_in,
    }
    config = dict(config)
    config["tokens"] = tokens
    save_config(config)
    return tokens


# --------------------------------------------------------------------------- #
# Transport: POST form, unwrap the {"status": .., "body": ..} envelope
# --------------------------------------------------------------------------- #


def _api_call(
    url: str,
    payload: Dict[str, Any],
    access_token: Optional[str],
    context: str,
) -> Dict[str, Any]:
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    if access_token:
        headers["Authorization"] = "Bearer %s" % access_token
    data = urlencode({k: v for k, v in payload.items() if v is not None}).encode("utf-8")
    request = Request(url, data=data, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=30) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise WithingsError("Withings %s failed: HTTP %s %s" % (context, exc.code, detail)) from None
    except URLError as exc:
        raise WithingsError("Withings %s failed: %s" % (context, exc.reason)) from None
    return _unwrap(raw, context)


def _unwrap(raw: Any, context: str) -> Dict[str, Any]:
    """Unwrap the Withings envelope; status != 0 is an API error."""
    if not isinstance(raw, dict) or "status" not in raw:
        raise WithingsError("Withings %s returned an unexpected payload (no status envelope)." % context)
    status = raw.get("status")
    if status != 0:
        raise WithingsError(
            "Withings %s failed: status=%s error=%s" % (context, status, raw.get("error") or "unknown")
        )
    body = raw.get("body")
    return body if isinstance(body, dict) else {}


# --------------------------------------------------------------------------- #
# Dates
# --------------------------------------------------------------------------- #

DateInput = Union[str, int, float, date_class, datetime, None]


def _to_date(value: DateInput, fallback_days_back: int) -> date_class:
    if value is None:
        return datetime.now(timezone.utc).date() - timedelta(days=fallback_days_back)
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date_class):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, tz=timezone.utc).date()
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        raise WithingsError("Cannot parse date %r (expected YYYY-MM-DD)." % (value,)) from None


def _day_start_unix(day: date_class) -> int:
    return int(datetime(day.year, day.month, day.day, tzinfo=timezone.utc).timestamp())


# --------------------------------------------------------------------------- #
# Measures: /measure action=getmeas (weight, body comp, blood pressure, hr)
# --------------------------------------------------------------------------- #


def fetch_measures(start_date: DateInput = None, end_date: DateInput = None) -> List[Dict[str, Any]]:
    """Body measures for the window as Observation-shaped dicts.

    Defaults to the last 30 days. Several readings of the same metric on one
    day collapse to the latest one (one observation per metric per day,
    matching the other connectors).
    """
    start_day = _to_date(start_date, fallback_days_back=30)
    end_day = _to_date(end_date, fallback_days_back=0)
    access_token = ensure_access_token()

    base_payload = {
        "action": "getmeas",
        "meastypes": ",".join(str(t) for t in sorted(MEASTYPES)),
        "category": 1,  # real measures only, not user goals
        "startdate": _day_start_unix(start_day),
        "enddate": _day_start_unix(end_day) + 86399,  # inclusive end of day
    }
    groups: List[Dict[str, Any]] = []
    offset: Optional[int] = None
    while True:
        payload = dict(base_payload)
        if offset:
            payload["offset"] = offset
        body = _api_call(MEASURE_URL, payload, access_token, context="getmeas")
        groups.extend(g for g in body.get("measuregrps", []) if isinstance(g, dict))
        if not body.get("more"):
            break
        offset = body.get("offset")
        if not offset:
            break

    # (metric, day) -> (group unix date, value); latest reading per day wins.
    buckets: Dict[Tuple[str, str], Tuple[int, float]] = {}
    for group in groups:
        group_ts = group.get("date")
        if not isinstance(group_ts, (int, float)):
            continue
        day = datetime.fromtimestamp(group_ts, tz=timezone.utc).date().isoformat()
        for measure in group.get("measures", []):
            if not isinstance(measure, dict):
                continue
            spec = MEASTYPES.get(measure.get("type"))
            if spec is None:
                continue  # unknown meastype — skip, never guess
            value = _decode_value(measure)
            if value is None:
                continue
            key = (spec[0], day)
            current = buckets.get(key)
            if current is None or group_ts >= current[0]:
                buckets[key] = (int(group_ts), value)

    by_metric = {name: (name, unit, kind, domain) for name, unit, kind, domain in MEASTYPES.values()}
    records = []
    for (metric, day), (_ts, value) in sorted(buckets.items()):
        _, unit, kind, domain = by_metric[metric]
        records.append(_obs(day, kind, metric, value, unit, domain))
    return records


def _decode_value(measure: Dict[str, Any]) -> Optional[float]:
    """Withings mantissa+exponent: real = value * 10 ** unit (75500, -3 -> 75.5)."""
    value = measure.get("value")
    exponent = measure.get("unit", 0)
    if not isinstance(value, (int, float)) or not isinstance(exponent, int):
        return None
    return round(value * (10 ** exponent), 3)


# --------------------------------------------------------------------------- #
# Sleep: /v2/sleep action=getsummary (Sleep Analyzer mat, ScanWatch)
# --------------------------------------------------------------------------- #


def fetch_sleep_summary(start_date: DateInput = None, end_date: DateInput = None) -> List[Dict[str, Any]]:
    """Nightly sleep summaries for the window as Observation-shaped dicts.

    Durations come back in seconds; converted to hours/minutes to line up with
    the Apple Health / Oura / WHOOP connectors. When ``total_sleep_time`` is
    absent, the deep+rem+light stages are summed instead.
    """
    start_day = _to_date(start_date, fallback_days_back=30)
    end_day = _to_date(end_date, fallback_days_back=0)
    access_token = ensure_access_token()

    base_payload = {
        "action": "getsummary",
        "startdateymd": start_day.isoformat(),
        "enddateymd": end_day.isoformat(),
        "data_fields": _SLEEP_DATA_FIELDS,
    }
    series: List[Dict[str, Any]] = []
    offset: Optional[int] = None
    while True:
        payload = dict(base_payload)
        if offset:
            payload["offset"] = offset
        body = _api_call(SLEEP_URL, payload, access_token, context="sleep getsummary")
        series.extend(s for s in body.get("series", []) if isinstance(s, dict))
        if not body.get("more"):
            break
        offset = body.get("offset")
        if not offset:
            break

    records: List[Dict[str, Any]] = []
    for night in sorted(series, key=lambda s: str(s.get("date") or "")):
        day = night.get("date")
        if not day:
            continue
        day = str(day)[:10]
        data = night.get("data") if isinstance(night.get("data"), dict) else {}
        seen_total = False
        for field, (metric, unit, kind, how) in _SLEEP_FIELDS.items():
            raw = data.get(field)
            if not isinstance(raw, (int, float)):
                continue
            if field == "total_sleep_time":
                seen_total = True
            records.append(_obs(day, kind, metric, _transform(float(raw), how), unit, "sleep"))
        if not seen_total:
            stages = [data.get(f) for f in _SLEEP_STAGE_SECONDS]
            present = [s for s in stages if isinstance(s, (int, float))]
            if present:
                total_h = _transform(float(sum(present)), "sec_to_h")
                records.append(_obs(day, "sleep_session", "sleep_duration_h", total_h, "h", "sleep"))
    return records


def _transform(value: float, how: str) -> float:
    if how == "sec_to_h":
        return round(value / 3600.0, 2)
    if how == "sec_to_min":
        return round(value / 60.0, 1)
    return round(value, 3)


# --------------------------------------------------------------------------- #
# Output shape (matches the other connectors)
# --------------------------------------------------------------------------- #


def _obs(day: str, kind: str, metric: str, value: float, unit: str, domain: str) -> Dict[str, Any]:
    return {
        "id": "obs-withings-%s-%s" % (metric, day),
        "record_type": "Observation",
        "source_id": SOURCE_ID,
        "title": "%s (%s)" % (metric.replace("_", " "), day),
        "summary": "%s = %s %s" % (metric, value, unit),
        "artifact_ids": [],
        "evidence_class": "personal",
        "confidence": CONF_DEVICE,
        "date": day,
        "tags": [SOURCE, domain],
        "metadata": {"connector": SOURCE, "source": SOURCE},
        "observation_kind": kind,
        "metric_name": metric,
        "value": value,
        "unit": unit,
    }


def summarize(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Quick rollup for the agent to read back: metrics found and date span."""
    metrics: Dict[str, int] = {}
    days = set()
    for r in records:
        metrics[r["metric_name"]] = metrics.get(r["metric_name"], 0) + 1
        if r.get("date"):
            days.add(r["date"])
    return {
        "source": SOURCE,
        "total_records": len(records),
        "metrics": dict(sorted(metrics.items())),
        "days_covered": len(days),
        "date_from": min(days) if days else None,
        "date_to": max(days) if days else None,
    }
