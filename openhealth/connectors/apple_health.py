"""Apple Health export → canonical daily Observations.

Apple Health exports a (often huge) `export.xml` inside a zip. We stream it with
`xml.etree.ElementTree.iterparse` so memory stays flat, map the common HealthKit
record types to our metrics, and aggregate to one Observation per day per metric.
Pure stdlib. Nothing leaves the machine.

This is the lowest-friction connector: anyone with an iPhone has this export.
"""

import os
import zipfile
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from xml.etree.ElementTree import iterparse

# HealthKit type -> (observation_kind, metric_name, unit, reducer, domain tag)
# reducer: "sum" | "mean" | "latest"
TYPE_MAP: Dict[str, Tuple[str, str, str, str, str]] = {
    "HKQuantityTypeIdentifierStepCount":                 ("steps", "steps", "count", "sum", "body"),
    "HKQuantityTypeIdentifierActiveEnergyBurned":        ("active_energy", "active_energy_kcal", "kcal", "sum", "body"),
    "HKQuantityTypeIdentifierAppleExerciseTime":         ("exercise", "exercise_min", "min", "sum", "body"),
    "HKQuantityTypeIdentifierHeartRate":                 ("heart_rate", "heart_rate_bpm", "bpm", "mean", "pulse"),
    "HKQuantityTypeIdentifierRestingHeartRate":          ("resting_hr", "resting_hr_bpm", "bpm", "mean", "pulse"),
    "HKQuantityTypeIdentifierHeartRateVariabilitySDNN":  ("hrv", "hrv_sdnn_ms", "ms", "mean", "pulse"),
    "HKQuantityTypeIdentifierBodyMass":                  ("weight", "weight_kg", "kg", "latest", "body"),
    "HKQuantityTypeIdentifierRespiratoryRate":           ("respiratory_rate", "respiratory_rate_rpm", "rpm", "mean", "pulse"),
}
SLEEP_TYPE = "HKCategoryTypeIdentifierSleepAnalysis"


def _parse_dt(s: str) -> Optional[datetime]:
    # HealthKit dates look like "2024-06-01 08:30:00 +0000"
    try:
        return datetime.strptime(s, "%Y-%m-%d %H:%M:%S %z")
    except (ValueError, TypeError):
        return None


def _to_kg(value: float, unit: str) -> float:
    return round(value * 0.45359237, 3) if unit and unit.lower() in ("lb", "lbs") else value


def _xml_stream(path: str):
    """Yield (event, elem) from export.xml, reading from a .zip or a raw .xml."""
    if path.lower().endswith(".zip"):
        with zipfile.ZipFile(path) as z:
            name = next((n for n in z.namelist() if n.endswith("export.xml")), None)
            if not name:
                raise ValueError("no export.xml inside the zip")
            with z.open(name) as fh:
                yield from iterparse(fh, events=("end",))
    else:
        with open(path, "rb") as fh:
            yield from iterparse(fh, events=("end",))


def import_apple_health(path: str, days_back: Optional[int] = None) -> List[Dict[str, Any]]:
    """Stream an Apple Health export and return daily Observation dicts."""
    # buckets[(metric_name)][date] -> list of values  (for quantities)
    buckets: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    meta: Dict[str, Tuple[str, str, str, str]] = {}  # metric -> (kind, unit, reducer, domain)
    sleep_secs: Dict[str, float] = defaultdict(float)  # date -> asleep seconds

    cutoff = None
    if days_back:
        cutoff = datetime.now().timestamp() - days_back * 86400

    count = 0
    for _, elem in _xml_stream(path):
        if elem.tag != "Record":
            continue
        rtype = elem.get("type", "")
        start = _parse_dt(elem.get("startDate", ""))
        if start is None:
            elem.clear(); continue
        if cutoff and start.timestamp() < cutoff:
            elem.clear(); continue
        day = start.date().isoformat()

        if rtype == SLEEP_TYPE:
            val = elem.get("value", "")
            if "Asleep" in val:  # asleep core/rem/deep/unspecified
                end = _parse_dt(elem.get("endDate", ""))
                if end:
                    sleep_secs[day] += max(0.0, (end - start).total_seconds())
        elif rtype in TYPE_MAP:
            kind, metric, unit, reducer, domain = TYPE_MAP[rtype]
            try:
                v = float(elem.get("value", ""))
            except (ValueError, TypeError):
                elem.clear(); continue
            if metric == "weight_kg":
                v = _to_kg(v, elem.get("unit", ""))
            buckets[metric][day].append(v)
            meta[metric] = (kind, unit, reducer, domain)
        count += 1
        elem.clear()

    records: List[Dict[str, Any]] = []

    def reduce(values: List[float], how: str) -> float:
        if how == "sum":
            return round(sum(values), 3)
        if how == "latest":
            return round(values[-1], 3)
        return round(sum(values) / len(values), 3)  # mean

    for metric, by_day in buckets.items():
        kind, unit, reducer, domain = meta[metric]
        for day, values in sorted(by_day.items()):
            value = reduce(values, reducer)
            records.append(_obs(day, kind, metric, value, unit, domain, len(values)))

    for day, secs in sorted(sleep_secs.items()):
        hours = round(secs / 3600.0, 2)
        records.append(_obs(day, "sleep_session", "sleep_duration_h", hours, "h", "sleep", 1))

    return records


def _obs(day, kind, metric, value, unit, domain, n) -> Dict[str, Any]:
    return {
        "id": "obs-applehealth-%s-%s" % (metric, day),
        "record_type": "Observation",
        "source_id": "apple-health",
        "title": "%s (%s)" % (metric.replace("_", " "), day),
        "summary": "%s = %s %s (%d samples)" % (metric, value, unit, n),
        "artifact_ids": [],
        "evidence_class": "personal",
        "confidence": 0.95,
        "date": day,
        "tags": ["apple-health", domain],
        "metadata": {"samples": n, "connector": "apple-health"},
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
        "total_records": len(records),
        "metrics": dict(sorted(metrics.items())),
        "days_covered": len(days),
        "date_from": min(days) if days else None,
        "date_to": max(days) if days else None,
    }
