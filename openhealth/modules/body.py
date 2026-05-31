"""Body module — weight trend, fasting windows, habit streaks.

Original, stdlib. Weight trend via least-squares slope (kg/week); fasting window
from the longest gap between eat events; habit streak from consecutive logged
days. Cautious, no diagnosis.
"""

from datetime import datetime
from typing import Any, Dict, List

from .base import ModuleResult, register
from .. import evidence


def _parse_dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def weight_trend(weights: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Latest, moving average, and least-squares slope in kg/week."""
    pts = sorted(weights, key=lambda w: w["date"])
    kgs = [float(w["kg"]) for w in pts]
    days = [(_parse_dt(w["date"]) - _parse_dt(pts[0]["date"])).total_seconds() / 86400.0 for w in pts]
    out: Dict[str, Any] = {"latest_kg": kgs[-1], "n": len(kgs)}
    window = kgs[-7:]
    out["moving_avg_kg"] = round(sum(window) / len(window), 3)
    if len(kgs) >= 2 and days[-1] > days[0]:
        n = len(kgs)
        mx = sum(days) / n
        my = sum(kgs) / n
        denom = sum((d - mx) ** 2 for d in days)
        slope_per_day = (sum((days[i] - mx) * (kgs[i] - my) for i in range(n)) / denom) if denom else 0.0
        out["trend_kg_per_week"] = round(slope_per_day * 7.0, 3)
    else:
        out["trend_kg_per_week"] = 0.0
    return out


def longest_fast_h(eat_events: List[str]) -> float:
    """Longest gap between consecutive eat events, in hours."""
    ts = sorted(_parse_dt(e) for e in eat_events)
    if len(ts) < 2:
        return 0.0
    gaps = [(ts[i + 1] - ts[i]).total_seconds() / 3600.0 for i in range(len(ts) - 1)]
    return round(max(gaps), 2)


def habit_streak(days_done: List[str]) -> int:
    """Count of the most recent consecutive calendar days marked done."""
    if not days_done:
        return 0
    ds = sorted({d[:10] for d in days_done})
    from datetime import date, timedelta
    streak = 1
    cur = date.fromisoformat(ds[-1])
    for prev in reversed(ds[:-1]):
        if date.fromisoformat(prev) == cur - timedelta(days=1):
            streak += 1
            cur = date.fromisoformat(prev)
        else:
            break
    return streak


class BodyModule:
    id = "body"
    name = "Body — weight trend, fasting, habits"
    domain = "body"
    summary = "Weight trend (kg/week), longest fasting window, and habit streaks."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "BodyInput",
            "type": "object",
            "properties": {
                "weights": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "required": ["date", "kg"],
                        "properties": {"date": {"type": "string"}, "kg": {"type": "number"}},
                    },
                },
                "eat_events": {"type": "array", "items": {"type": "string"}, "description": "ISO datetimes of meals"},
                "habit_days": {"type": "array", "items": {"type": "string"}, "description": "ISO dates a habit was done"},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        metrics: List[Dict[str, Any]] = []
        insights: List[Dict[str, Any]] = []
        notes: List[str] = []

        weights = payload.get("weights") or []
        if weights:
            wt = weight_trend(weights)
            last_date = sorted(weights, key=lambda w: w["date"])[-1]["date"][:10]
            metrics.append({
                "id": "obs-body-weight",
                "record_type": "Observation",
                "source_id": "body",
                "title": "Weight",
                "summary": "Latest %.1f kg, 7-pt avg %.1f kg, trend %.2f kg/week." % (wt["latest_kg"], wt["moving_avg_kg"], wt["trend_kg_per_week"]),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.95,
                "date": last_date,
                "tags": ["body", "weight"],
                "metadata": wt,
                "observation_kind": "weight",
                "metric_name": "weight_kg",
                "value": wt["latest_kg"],
                "unit": "kg",
            })
            if wt["n"] >= 4 and abs(wt["trend_kg_per_week"]) >= 0.25:
                direction = "down" if wt["trend_kg_per_week"] < 0 else "up"
                txt = "Weight is trending %s about %.2f kg/week recently." % (direction, abs(wt["trend_kg_per_week"]))
                conf = evidence.Confidence.C3
                insights.append({
                    "id": "insight-body-weight-trend",
                    "record_type": "InsightHypothesis",
                    "source_id": "body",
                    "title": "Weight trend",
                    "summary": evidence.frame_statement(txt, conf),
                    "artifact_ids": [],
                    "evidence_class": "derived-hypothesis",
                    "confidence": evidence.confidence_to_numeric(conf),
                    "date": last_date,
                    "tags": ["body", "weight", "review-needed"],
                    "metadata": wt,
                    "statement": txt,
                    "evidence_record_ids": ["obs-body-weight"],
                    "open_questions": ["Is this change intentional?", "What changed in routine recently?"],
                })

        eat = payload.get("eat_events") or []
        if len(eat) >= 2:
            fast_h = longest_fast_h(eat)
            metrics.append({
                "id": "obs-body-fast",
                "record_type": "Observation",
                "source_id": "body",
                "title": "Longest fasting window",
                "summary": "Longest gap between meals: %.1f h." % fast_h,
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.9,
                "tags": ["body", "fasting"],
                "metadata": {"longest_fast_h": fast_h},
                "observation_kind": "fasting_window",
                "metric_name": "longest_fast_h",
                "value": fast_h,
                "unit": "h",
            })

        habit = payload.get("habit_days") or []
        if habit:
            streak = habit_streak(habit)
            metrics.append({
                "id": "obs-body-habit",
                "record_type": "Observation",
                "source_id": "body",
                "title": "Habit streak",
                "summary": "Current streak: %d day(s)." % streak,
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.95,
                "tags": ["body", "habit"],
                "metadata": {"streak_days": streak},
                "observation_kind": "habit_streak",
                "metric_name": "habit_streak_days",
                "value": streak,
                "unit": "days",
            })

        if not metrics:
            notes.append("no weights, eat_events or habit_days provided")
        return ModuleResult(metrics=metrics, insights=insights, notes=notes)


register(BodyModule())
