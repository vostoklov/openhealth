"""Sleep & Circadian module — behavioral sleep markers and a cautious phase read.

From sleep onset/offset times we compute *behavioral* markers only: duration,
midsleep, and social jetlag (Wittmann/Roenneberg). A circadian-phase estimate is
offered as a rough proxy (DLMO ~ onset - 2 h) and is explicitly an assumption,
not a measurement — capped at C2 and disclosed. Sleep staging and true phase
need lab/PSG or melatonin assay we do not have. Pure stdlib.
"""

from datetime import datetime
from typing import Any, Dict, List

from .base import ModuleResult, register
from .. import evidence


def _parse(dt: str) -> datetime:
    return datetime.fromisoformat(dt.replace("Z", "+00:00"))


def _clock_hours(dt: datetime) -> float:
    """Time-of-day in hours [0,24)."""
    return dt.hour + dt.minute / 60.0 + dt.second / 3600.0


def session_markers(onset: str, offset: str) -> Dict[str, float]:
    o = _parse(onset)
    f = _parse(offset)
    dur_h = (f - o).total_seconds() / 3600.0
    if dur_h <= 0:
        raise ValueError("offset must be after onset")
    midsleep = o + (f - o) / 2
    return {
        "duration_h": round(dur_h, 3),
        "midsleep_clock_h": round(_clock_hours(midsleep), 3),
        "onset_clock_h": round(_clock_hours(o), 3),
        "dlmo_proxy_clock_h": round((_clock_hours(o) - 2.0) % 24.0, 3),
    }


def social_jetlag(sessions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """|mean midsleep on free days - mean midsleep on work days| in hours.

    Each session may carry "workday": bool. Returns None components if a class
    is missing.
    """
    work, free = [], []
    for s in sessions:
        m = session_markers(s["onset"], s["offset"])["midsleep_clock_h"]
        (work if s.get("workday") else free).append(m)
    out: Dict[str, Any] = {
        "mean_midsleep_work_h": round(sum(work) / len(work), 3) if work else None,
        "mean_midsleep_free_h": round(sum(free) / len(free), 3) if free else None,
    }
    if work and free:
        out["social_jetlag_h"] = round(abs(out["mean_midsleep_free_h"] - out["mean_midsleep_work_h"]), 3)
    else:
        out["social_jetlag_h"] = None
    return out


class SleepModule:
    id = "sleep"
    name = "Sleep & Circadian — duration, midsleep, social jetlag"
    domain = "sleep"
    summary = "Behavioral sleep markers and a rough circadian-phase prompt (not lab phase)."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "SleepInput",
            "type": "object",
            "required": ["sessions"],
            "properties": {
                "sessions": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["onset", "offset"],
                        "properties": {
                            "onset": {"type": "string", "description": "ISO datetime asleep"},
                            "offset": {"type": "string", "description": "ISO datetime awake"},
                            "workday": {"type": "boolean"},
                            "date": {"type": "string"},
                        },
                    },
                }
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        sessions = payload.get("sessions", [])
        if not sessions:
            raise ValueError("need at least one sleep session")

        metrics: List[Dict[str, Any]] = []
        durations: List[float] = []
        for i, s in enumerate(sessions):
            mk = session_markers(s["onset"], s["offset"])
            durations.append(mk["duration_h"])
            date = s.get("date") or s["onset"][:10]
            metrics.append({
                "id": "obs-sleep-%s-%d" % (date, i),
                "record_type": "Observation",
                "source_id": "sleep",
                "title": "Sleep session",
                "summary": "Slept %.1f h, midsleep %.1f h." % (mk["duration_h"], mk["midsleep_clock_h"]),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.95,
                "date": date,
                "tags": ["sleep"],
                "metadata": mk,
                "observation_kind": "sleep_session",
                "metric_name": "duration_h",
                "value": mk["duration_h"],
                "unit": "h",
            })

        sj = social_jetlag(sessions)
        insights: List[Dict[str, Any]] = []

        # Circadian phase: behavioral proxy only -> C2, framed as a question.
        if metrics:
            conf = evidence.cap_personal_pattern(evidence.Confidence.C3, validated_switches=0)
            phase_text = (
                "Your midsleep sits near %.1f h. From sleep timing alone this is a rough "
                "circadian read (a behavioral proxy, not measured phase)."
                % (sum(m["metadata"]["midsleep_clock_h"] for m in metrics) / len(metrics))
            )
            insights.append({
                "id": "insight-sleep-phase-%s" % (sessions[0].get("date") or sessions[0]["onset"][:10]),
                "record_type": "InsightHypothesis",
                "source_id": "sleep",
                "title": "Rough circadian phase",
                "summary": evidence.frame_statement(phase_text, conf),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(conf),
                "tags": ["sleep", "circadian", "review-needed"],
                "metadata": {"limits": "sleep timing only; no melatonin/light measured"},
                "statement": phase_text,
                "evidence_record_ids": [m["id"] for m in metrics],
                "open_questions": ["Do you track light exposure or use a wearable for phase?"],
            })

        if sj.get("social_jetlag_h") is not None and sj["social_jetlag_h"] >= 1.0:
            conf = evidence.Confidence.C3
            sj_text = (
                "Midsleep shifts about %.1f h between work and free days (social jetlag). "
                "Larger shifts are linked in research to worse rest." % sj["social_jetlag_h"]
            )
            insights.append({
                "id": "insight-sleep-sjl",
                "record_type": "InsightHypothesis",
                "source_id": "sleep",
                "title": "Social jetlag",
                "summary": evidence.frame_statement(sj_text, conf),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(conf),
                "tags": ["sleep", "social-jetlag", "review-needed"],
                "metadata": sj,
                "statement": sj_text,
                "evidence_record_ids": [m["id"] for m in metrics],
                "open_questions": ["Could you nudge weekend wake time closer to weekdays?"],
            })

        notes = ["duration mean %.2f h over %d session(s)" % (sum(durations) / len(durations), len(durations))]
        return ModuleResult(metrics=metrics, insights=insights, notes=notes)


register(SleepModule())
