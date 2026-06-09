"""Garmin export → canonical daily Observations.

Garmin data reaches users in two shapes:

* **JSON** — the Garmin Health API / "Export Your Data" archive uses one object
  per daily summary with PascalCase keys (``CalendarDate``, ``LastNightAvg``,
  ``DurationInSeconds`` ...). Summaries come in typed families: Daily, Sleep,
  HRV, Stress. A bulk export is usually a list of such objects, or an object
  keyed by family.
* **CSV** — Garmin Connect's web UI exports per-metric CSV files (sleep, resting
  heart rate, stress, body battery) with one row per day and human-readable
  headers.

This connector accepts either. Feed it a ``.json`` or ``.csv`` path and it
returns Observation-shaped dicts, one per day per metric.

Clean-room implementation written from the public Garmin Health API data-model
field documentation. Pure stdlib, nothing leaves the machine. Garmin durations
are in **seconds**; sleep totals are converted to hours to match the other
connectors. HRV (``LastNightAvg``, rMSSD-style ms) is surfaced because it is the
signal this project cares about most.

Entry point: ``import_garmin(path, days_back=None) -> list[dict]``.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SOURCE = "garmin"
SOURCE_ID = "garmin"

CONF_RAW = 0.9
CONF_SCORE = 0.8

# Canonical metric spec: metric_name -> (observation_kind, unit, domain, confidence)
_METRIC_SPEC: Dict[str, Tuple[str, str, str, float]] = {
    "sleep_duration_h":   ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_deep_h":       ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_rem_h":        ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_light_h":      ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_awake_h":      ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_score":        ("sleep_score", "score", "sleep", CONF_SCORE),
    "hrv_rmssd_ms":       ("hrv", "ms", "pulse", CONF_RAW),
    "hrv_5min_high_ms":   ("hrv", "ms", "pulse", CONF_RAW),
    "resting_hr_bpm":     ("resting_hr", "bpm", "pulse", CONF_RAW),
    "avg_heart_rate_bpm": ("heart_rate", "bpm", "pulse", CONF_RAW),
    "max_heart_rate_bpm": ("heart_rate", "bpm", "pulse", CONF_RAW),
    "respiratory_rate_rpm": ("respiratory_rate", "rpm", "pulse", CONF_RAW),
    "spo2_pct":           ("spo2", "%", "pulse", CONF_RAW),
    "stress_avg":         ("stress", "level", "recovery", CONF_RAW),
    "body_battery_high":  ("body_battery", "level", "recovery", CONF_RAW),
    "body_battery_low":   ("body_battery", "level", "recovery", CONF_RAW),
    "steps":              ("steps", "count", "body", CONF_RAW),
    "active_energy_kcal": ("active_energy", "kcal", "body", CONF_RAW),
    "total_energy_kcal":  ("total_energy", "kcal", "body", CONF_RAW),
    "distance_m":         ("distance", "m", "body", CONF_RAW),
    "floors_climbed":     ("floors", "count", "body", CONF_RAW),
}

# Garmin field name (normalised to snake_case) -> (canonical_metric, transform).
# Covers both PascalCase JSON keys (lower-cased) and CSV/web header variants.
_FIELD_MAP: Dict[str, Tuple[str, str]] = {
    # --- sleep ---
    "durationinseconds": ("sleep_duration_h", "sec_to_h"),
    "sleeptimeseconds": ("sleep_duration_h", "sec_to_h"),
    "total_sleep": ("sleep_duration_h", "hms_or_h"),
    "sleep_time": ("sleep_duration_h", "hms_or_h"),
    "deepsleepdurationinseconds": ("sleep_deep_h", "sec_to_h"),
    "deep_sleep": ("sleep_deep_h", "hms_or_h"),
    "remsleepinseconds": ("sleep_rem_h", "sec_to_h"),
    "rem_sleep": ("sleep_rem_h", "hms_or_h"),
    "lightsleepdurationinseconds": ("sleep_light_h", "sec_to_h"),
    "light_sleep": ("sleep_light_h", "hms_or_h"),
    "awakedurationinseconds": ("sleep_awake_h", "sec_to_h"),
    "awake": ("sleep_awake_h", "hms_or_h"),
    "overallsleepscore": ("sleep_score", "ident"),
    "sleep_score": ("sleep_score", "ident"),
    "sleepscore": ("sleep_score", "ident"),
    # --- hrv (the metric this project optimises for) ---
    "lastnightavg": ("hrv_rmssd_ms", "ident"),
    "hrv": ("hrv_rmssd_ms", "ident"),
    "avg_hrv": ("hrv_rmssd_ms", "ident"),
    "hrv_rmssd": ("hrv_rmssd_ms", "ident"),
    "lastnight5minhigh": ("hrv_5min_high_ms", "ident"),
    # --- heart rate ---
    "restingheartrateinbeatsperminute": ("resting_hr_bpm", "ident"),
    "restingheartrate": ("resting_hr_bpm", "ident"),
    "resting_heart_rate": ("resting_hr_bpm", "ident"),
    "averageheartrateinbeatsperminute": ("avg_heart_rate_bpm", "ident"),
    "averageheartrate": ("avg_heart_rate_bpm", "ident"),
    "maxheartrateinbeatsperminute": ("max_heart_rate_bpm", "ident"),
    "maxheartrate": ("max_heart_rate_bpm", "ident"),
    # --- respiration / spo2 ---
    "averagerespirationvalue": ("respiratory_rate_rpm", "ident"),
    "respiration": ("respiratory_rate_rpm", "ident"),
    "averagespo2value": ("spo2_pct", "ident"),
    "spo2": ("spo2_pct", "ident"),
    "averagespo2": ("spo2_pct", "ident"),
    # --- stress / body battery ---
    "averagestresslevel": ("stress_avg", "ident"),
    "avg_stress_level": ("stress_avg", "ident"),
    "stress": ("stress_avg", "ident"),
    "stress_avg": ("stress_avg", "ident"),
    "bodybatterychargedvalue": ("body_battery_high", "ident"),
    "body_battery_high": ("body_battery_high", "ident"),
    "max_body_battery": ("body_battery_high", "ident"),
    "bodybatterydrainedvalue": ("body_battery_low", "ident"),
    "body_battery_low": ("body_battery_low", "ident"),
    "min_body_battery": ("body_battery_low", "ident"),
    # --- activity ---
    "steps": ("steps", "ident"),
    "totalsteps": ("steps", "ident"),
    "activekilocalories": ("active_energy_kcal", "ident"),
    "active_calories": ("active_energy_kcal", "ident"),
    "bmrkilocalories": ("total_energy_kcal", "ident"),
    "calories": ("total_energy_kcal", "ident"),
    "total_calories": ("total_energy_kcal", "ident"),
    "distanceinmeters": ("distance_m", "ident"),
    "distance": ("distance_m", "ident"),
    "floorsclimbed": ("floors_climbed", "ident"),
    "floors": ("floors_climbed", "ident"),
}

_DATE_KEYS = (
    "calendardate",
    "calendar_date",
    "date",
    "day",
    "summarydate",
    "summary_date",
    "startdate",
)


def _norm_key(key: str) -> str:
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _parse_date(raw: str) -> Optional[str]:
    if not raw:
        return None
    raw = raw.strip()
    head = raw[:10]
    try:
        return datetime.strptime(head, "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass
    # US-style CSV dates (Garmin Connect web sometimes uses M/D/YYYY).
    for fmt in ("%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d"):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            continue
    cleaned = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).date().isoformat()
    except ValueError:
        return None


def _hms_to_hours(raw: str) -> Optional[float]:
    """Parse a Garmin web duration like '7h 32m', '7:32', or '7.5' into hours."""
    raw = raw.strip().lower()
    if not raw:
        return None
    if "h" in raw or "m" in raw:
        hours = 0.0
        token = raw.replace("h", " h ").replace("m", " m ").split()
        prev = None
        for part in token:
            if part in ("h", "m") and prev is not None:
                try:
                    val = float(prev)
                except ValueError:
                    prev = None
                    continue
                hours += val if part == "h" else val / 60.0
                prev = None
            else:
                prev = part
        return round(hours, 2) if hours else None
    if ":" in raw:
        bits = raw.split(":")
        try:
            nums = [float(b) for b in bits]
        except ValueError:
            return None
        if len(nums) == 2:
            return round(nums[0] + nums[1] / 60.0, 2)
        if len(nums) == 3:
            return round(nums[0] + nums[1] / 60.0 + nums[2] / 3600.0, 2)
        return None
    # Bare number: already hours.
    try:
        return round(float(raw), 2)
    except ValueError:
        return None


def _to_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    if isinstance(raw, str):
        raw = raw.replace(",", "")
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _transform(raw: Any, how: str) -> Optional[float]:
    if how == "sec_to_h":
        v = _to_float(raw)
        return round(v / 3600.0, 2) if v is not None else None
    if how == "hms_or_h":
        if isinstance(raw, (int, float)):
            # Numeric without explicit unit: Garmin JSON gives seconds, treat as such.
            return round(float(raw) / 3600.0, 2)
        return _hms_to_hours(str(raw))
    v = _to_float(raw)
    return round(v, 3) if v is not None else None


def _find_date(normalised: Dict[str, Any]) -> Optional[str]:
    for key in _DATE_KEYS:
        if key in normalised:
            day = _parse_date(str(normalised[key]))
            if day:
                return day
    return None


def _emit(buckets: Dict[Tuple[str, str], float], day: str, metric: str, value: Optional[float]) -> None:
    if day is None or value is None or metric not in _METRIC_SPEC:
        return
    buckets[(metric, day)] = value


def _ingest_record(buckets: Dict[Tuple[str, str], float], record: Dict[str, Any]) -> None:
    """Map one Garmin daily summary (JSON object or CSV row) to canonical metrics."""
    normalised = {_norm_key(str(k)): v for k, v in record.items()}
    day = _find_date(normalised)
    if not day:
        return
    for key, raw_value in normalised.items():
        spec = _FIELD_MAP.get(key)
        if spec is None:
            continue
        metric, how = spec
        _emit(buckets, day, metric, _transform(raw_value, how))


def _ingest_json(buckets: Dict[Tuple[str, str], float], payload: Any) -> None:
    """Handle bulk JSON: a list of summaries, or an object keyed by summary family."""
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _ingest_record(buckets, item)
        return
    if isinstance(payload, dict):
        consumed = False
        # Object keyed by family: {"sleep": [...], "hrv": [...], "stress": [...]}.
        for value in payload.values():
            if isinstance(value, list) and value and isinstance(value[0], dict):
                for item in value:
                    if isinstance(item, dict):
                        _ingest_record(buckets, item)
                consumed = True
        # V2-style {"data": [...]} envelope.
        if isinstance(payload.get("data"), list):
            for item in payload["data"]:
                if isinstance(item, dict):
                    _ingest_record(buckets, item)
            consumed = True
        # A single flat daily-summary object.
        if not consumed:
            _ingest_record(buckets, payload)


def _load_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def import_garmin(path: str, days_back: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read a Garmin export (JSON or CSV) and return daily Observation dicts.

    Parameters
    ----------
    path:
        Path to a Garmin ``.json`` or ``.csv`` export.
    days_back:
        If set, drop records older than ``days_back`` days from today.
    """
    if not os.path.exists(path):
        raise FileNotFoundError("Garmin export not found: %s" % path)

    buckets: Dict[Tuple[str, str], float] = {}

    lower = path.lower()
    if lower.endswith(".json"):
        _ingest_json(buckets, _load_json(path))
    elif lower.endswith(".csv"):
        for row in _load_csv(path):
            _ingest_record(buckets, row)
    else:
        with open(path, encoding="utf-8-sig") as fh:
            head = fh.read(1).lstrip()
        if head in ("{", "["):
            _ingest_json(buckets, _load_json(path))
        else:
            for row in _load_csv(path):
                _ingest_record(buckets, row)

    cutoff: Optional[str] = None
    if days_back:
        cutoff = datetime.fromtimestamp(
            datetime.now().timestamp() - days_back * 86400
        ).date().isoformat()

    records: List[Dict[str, Any]] = []
    for (metric, day), value in sorted(buckets.items()):
        if cutoff and day < cutoff:
            continue
        kind, unit, domain, confidence = _METRIC_SPEC[metric]
        records.append(_obs(day, kind, metric, value, unit, domain, confidence))
    return records


def _obs(day: str, kind: str, metric: str, value: float, unit: str, domain: str, confidence: float) -> Dict[str, Any]:
    return {
        "id": "obs-garmin-%s-%s" % (metric, day),
        "record_type": "Observation",
        "source_id": SOURCE_ID,
        "title": "%s (%s)" % (metric.replace("_", " "), day),
        "summary": "%s = %s %s" % (metric, value, unit),
        "artifact_ids": [],
        "evidence_class": "personal",
        "confidence": confidence,
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
    metrics: Dict[str, int] = defaultdict(int)
    days = set()
    for r in records:
        metrics[r["metric_name"]] += 1
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
