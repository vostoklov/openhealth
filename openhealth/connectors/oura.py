"""Oura ring export → canonical daily Observations.

Oura lets a member export their data from the Membership Hub as a **CSV** file
(one row per day per summary type) or as **JSON** (the same shape the Oura API
V2 returns: a top-level object keyed by ``sleep`` / ``readiness`` / ``activity``,
each a list of daily summaries). This connector accepts either: feed it the path
to a ``.csv`` or ``.json`` export and it returns Observation-shaped dicts, one per
day per metric.

Clean-room implementation written from the public Oura export / API V2 field
documentation. Pure stdlib, nothing leaves the machine. Durations in Oura exports
are expressed in **seconds**; we convert sleep totals to hours so they line up
with the Apple Health / WHOOP connectors.

Entry point: ``import_oura(path, days_back=None) -> list[dict]``.
"""

import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SOURCE = "oura"
SOURCE_ID = "oura"

# Oura summary "score" fields are 0-100 indices. We give them slightly lower
# confidence than the raw physiological signals (hr/hrv) which Oura measures
# directly.
CONF_RAW = 0.9
CONF_SCORE = 0.8

# Canonical metric spec: metric_name -> (observation_kind, unit, domain, confidence)
_METRIC_SPEC: Dict[str, Tuple[str, str, str, float]] = {
    "sleep_duration_h":   ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_deep_h":       ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_rem_h":        ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_light_h":      ("sleep_session", "h", "sleep", CONF_RAW),
    "sleep_latency_min":  ("sleep_session", "min", "sleep", CONF_RAW),
    "sleep_efficiency":   ("sleep_session", "%", "sleep", CONF_RAW),
    "sleep_score":        ("sleep_score", "score", "sleep", CONF_SCORE),
    "resting_hr_bpm":     ("resting_hr", "bpm", "pulse", CONF_RAW),
    "heart_rate_avg_bpm": ("heart_rate", "bpm", "pulse", CONF_RAW),
    "hrv_rmssd_ms":       ("hrv", "ms", "pulse", CONF_RAW),
    "respiratory_rate_rpm": ("respiratory_rate", "rpm", "pulse", CONF_RAW),
    "body_temp_delta_c":  ("body_temperature", "c", "pulse", CONF_RAW),
    "readiness_score":    ("readiness_score", "score", "recovery", CONF_SCORE),
    "activity_score":     ("activity_score", "score", "body", CONF_SCORE),
    "steps":              ("steps", "count", "body", CONF_RAW),
    "active_energy_kcal": ("active_energy", "kcal", "body", CONF_RAW),
    "total_energy_kcal":  ("total_energy", "kcal", "body", CONF_RAW),
}

# Source field aliases -> canonical metric. Oura CSV exports flatten everything
# into one wide row, while the JSON/API shape nests by summary type; both reuse
# these field names, so a single alias table covers both.
_SLEEP_FIELDS: Dict[str, Tuple[str, str]] = {
    # source_field -> (canonical_metric, transform)
    "total": ("sleep_duration_h", "sec_to_h"),
    "total_sleep_duration": ("sleep_duration_h", "sec_to_h"),
    "duration": ("sleep_duration_h", "sec_to_h"),
    "deep": ("sleep_deep_h", "sec_to_h"),
    "deep_sleep_duration": ("sleep_deep_h", "sec_to_h"),
    "rem": ("sleep_rem_h", "sec_to_h"),
    "rem_sleep_duration": ("sleep_rem_h", "sec_to_h"),
    "light": ("sleep_light_h", "sec_to_h"),
    "light_sleep_duration": ("sleep_light_h", "sec_to_h"),
    "onset_latency": ("sleep_latency_min", "sec_to_min"),
    "latency": ("sleep_latency_min", "sec_to_min"),
    "efficiency": ("sleep_efficiency", "ident"),
    "hr_average": ("heart_rate_avg_bpm", "ident"),
    "average_heart_rate": ("heart_rate_avg_bpm", "ident"),
    "hr_lowest": ("resting_hr_bpm", "ident"),
    "lowest_heart_rate": ("resting_hr_bpm", "ident"),
    "rmssd": ("hrv_rmssd_ms", "ident"),
    "average_hrv": ("hrv_rmssd_ms", "ident"),
    "breath_average": ("respiratory_rate_rpm", "ident"),
    "average_breath": ("respiratory_rate_rpm", "ident"),
    "temperature_delta": ("body_temp_delta_c", "ident"),
}
_READINESS_FIELDS: Dict[str, Tuple[str, str]] = {
    "score": ("readiness_score", "ident"),
    "resting_heart_rate": ("resting_hr_bpm", "ident"),
}
_ACTIVITY_FIELDS: Dict[str, Tuple[str, str]] = {
    "score": ("activity_score", "ident"),
    "steps": ("steps", "ident"),
    "daily_movement": ("steps", "ident"),  # fallback when steps absent (meters, but kept as movement count)
    "cal_active": ("active_energy_kcal", "ident"),
    "active_calories": ("active_energy_kcal", "ident"),
    "cal_total": ("total_energy_kcal", "ident"),
    "total_calories": ("total_energy_kcal", "ident"),
}

# When a CSV row is generic (the Membership Hub "trends" export) we cannot tell
# sleep "score" from readiness "score". Prefixed columns disambiguate:
# "Sleep Score", "readiness_score", "activity_score", etc.
_SCORE_PREFIXES = {
    "sleep": "sleep_score",
    "readiness": "readiness_score",
    "activity": "activity_score",
}


def _transform(value: float, how: str) -> float:
    if how == "sec_to_h":
        return round(value / 3600.0, 2)
    if how == "sec_to_min":
        return round(value / 60.0, 1)
    return round(value, 3)


def _parse_date(raw: str) -> Optional[str]:
    """Normalise any Oura date/datetime string to an ISO date (YYYY-MM-DD)."""
    if not raw:
        return None
    raw = raw.strip()
    # Pure date already.
    head = raw[:10]
    for fmt in ("%Y-%m-%d",):
        try:
            return datetime.strptime(head, fmt).date().isoformat()
        except ValueError:
            pass
    # Datetime / ISO with offset (bedtime_start style: 2024-06-01T23:10:00+02:00).
    cleaned = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(cleaned).date().isoformat()
    except ValueError:
        return None


def _to_float(raw: Any) -> Optional[float]:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _norm_key(key: str) -> str:
    """'Sleep Score' / 'HR Average' -> 'sleep_score' / 'hr_average'."""
    return key.strip().lower().replace(" ", "_").replace("-", "_")


def _emit(buckets: Dict[Tuple[str, str], float], day: str, metric: str, value: Optional[float]) -> None:
    if day is None or value is None or metric not in _METRIC_SPEC:
        return
    # Last write wins per (metric, day); Oura exports are one summary per day.
    buckets[(metric, day)] = value


def _ingest_summary(
    buckets: Dict[Tuple[str, str], float],
    row: Dict[str, Any],
    field_map: Dict[str, Tuple[str, str]],
    *,
    score_metric: Optional[str] = None,
    date_value: Optional[str] = None,
) -> None:
    """Map one daily summary dict onto canonical metrics.

    ``score_metric`` overrides the generic ``score`` field for typed summaries
    (sleep/readiness/activity each have their own ``score``).
    """
    day = date_value
    if day is None:
        for date_key in ("summary_date", "day", "date", "calendar_date", "calendardate"):
            if date_key in row:
                day = _parse_date(str(row[date_key]))
                if day:
                    break
    if not day:
        return
    for raw_key, raw_value in row.items():
        key = _norm_key(str(raw_key))
        if key == "score" and score_metric:
            _emit(buckets, day, score_metric, _to_float(raw_value))
            continue
        spec = field_map.get(key)
        if spec is None:
            continue
        metric, how = spec
        fval = _to_float(raw_value)
        if fval is None:
            continue
        _emit(buckets, day, metric, _transform(fval, how))


def _ingest_csv_row(buckets: Dict[Tuple[str, str], float], row: Dict[str, Any]) -> None:
    """A wide 'trends' CSV row may mix sleep/readiness/activity columns.

    We feed it through every field map and resolve prefixed score columns
    ('sleep_score', 'readiness_score', 'activity_score') explicitly so the three
    distinct scores never collide on a bare 'score'.
    """
    day = None
    for date_key in ("summary_date", "day", "date", "calendar_date", "calendardate"):
        for raw_key in row:
            if _norm_key(str(raw_key)) == date_key:
                day = _parse_date(str(row[raw_key]))
                break
        if day:
            break
    if not day:
        return

    normalised = {_norm_key(str(k)): v for k, v in row.items()}

    # Generic field maps (sleep stage/hr/hrv, activity steps/cals).
    for field_map in (_SLEEP_FIELDS, _ACTIVITY_FIELDS):
        for src_field, (metric, how) in field_map.items():
            if src_field in normalised:
                fval = _to_float(normalised[src_field])
                if fval is not None:
                    _emit(buckets, day, metric, _transform(fval, how))

    # Explicit prefixed score columns.
    for prefix, metric in _SCORE_PREFIXES.items():
        for candidate in (metric, "%s_score" % prefix, "score_%s" % prefix):
            if candidate in normalised:
                _emit(buckets, day, metric, _to_float(normalised[candidate]))
                break

    # Standalone resting hr / hrv columns sometimes appear at top level.
    for src_field, (metric, how) in _READINESS_FIELDS.items():
        if src_field in normalised and src_field != "score":
            fval = _to_float(normalised[src_field])
            if fval is not None:
                _emit(buckets, day, metric, _transform(fval, how))


def _load_csv(path: str) -> List[Dict[str, Any]]:
    with open(path, newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def _load_json(path: str) -> Any:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _ingest_json(buckets: Dict[Tuple[str, str], float], payload: Any) -> None:
    """Handle the Oura API V2 / JSON export shape.

    Recognised top-level containers (any subset):
      {"sleep": [...], "readiness": [...], "activity": [...]}
    Also tolerates the V2 ``{"data": [...]}`` envelope and bare lists.
    """
    def each(container: Any):
        if isinstance(container, dict) and "data" in container and isinstance(container["data"], list):
            return container["data"]
        if isinstance(container, list):
            return container
        return []

    if isinstance(payload, dict):
        if "sleep" in payload:
            for item in each(payload["sleep"]):
                if isinstance(item, dict):
                    _ingest_summary(buckets, item, _SLEEP_FIELDS, score_metric="sleep_score")
        if "readiness" in payload:
            for item in each(payload["readiness"]):
                if isinstance(item, dict):
                    _ingest_summary(buckets, item, _READINESS_FIELDS, score_metric="readiness_score")
        if "activity" in payload or "daily_activity" in payload:
            for item in each(payload.get("activity", payload.get("daily_activity"))):
                if isinstance(item, dict):
                    _ingest_summary(buckets, item, _ACTIVITY_FIELDS, score_metric="activity_score")
        # A flat object that is itself one wide daily summary.
        if not any(k in payload for k in ("sleep", "readiness", "activity", "daily_activity")):
            _ingest_csv_row(buckets, payload)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                _ingest_csv_row(buckets, item)


def import_oura(path: str, days_back: Optional[int] = None) -> List[Dict[str, Any]]:
    """Read an Oura export (CSV or JSON) and return daily Observation dicts.

    Parameters
    ----------
    path:
        Path to an Oura ``.csv`` or ``.json`` export.
    days_back:
        If set, drop records older than ``days_back`` days from today.
    """
    if not os.path.exists(path):
        raise FileNotFoundError("Oura export not found: %s" % path)

    buckets: Dict[Tuple[str, str], float] = {}

    lower = path.lower()
    if lower.endswith(".json"):
        _ingest_json(buckets, _load_json(path))
    elif lower.endswith(".csv"):
        for row in _load_csv(path):
            _ingest_csv_row(buckets, row)
    else:
        # Unknown extension: sniff content (JSON object/array vs CSV header).
        with open(path, encoding="utf-8-sig") as fh:
            head = fh.read(1).lstrip()
        if head in ("{", "["):
            _ingest_json(buckets, _load_json(path))
        else:
            for row in _load_csv(path):
                _ingest_csv_row(buckets, row)

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
        "id": "obs-oura-%s-%s" % (metric, day),
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
