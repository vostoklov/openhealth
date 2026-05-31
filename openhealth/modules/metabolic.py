"""Metabolic module — glucose summary, time-in-range, a cautious read.

From glucose readings (mg/dL) we compute mean, time-in-range (70-180 mg/dL, the
standard CGM target), and a Glucose Management Indicator (GMI = 3.31 +
0.02392*mean, Bergenstal 2018). Critical values raise a red flag and are not
interpreted. No diagnosis. Pure stdlib.
"""

from typing import Any, Dict, List

from .base import ModuleResult, register
from .. import evidence

TIR_LOW = 70.0
TIR_HIGH = 180.0


def summarize_glucose(readings_mg_dl: List[float]) -> Dict[str, Any]:
    vals = [float(v) for v in readings_mg_dl]
    n = len(vals)
    mean = sum(vals) / n
    in_range = sum(1 for v in vals if TIR_LOW <= v <= TIR_HIGH)
    return {
        "n": n,
        "mean_mg_dl": round(mean, 2),
        "time_in_range_pct": round(100.0 * in_range / n, 1),
        "below_pct": round(100.0 * sum(1 for v in vals if v < TIR_LOW) / n, 1),
        "above_pct": round(100.0 * sum(1 for v in vals if v > TIR_HIGH) / n, 1),
        "gmi_pct": round(3.31 + 0.02392 * mean, 2),
    }


class MetabolicModule:
    id = "metabolic"
    name = "Metabolic — glucose, time-in-range"
    domain = "metabolic"
    summary = "Glucose mean, time-in-range and GMI from readings (mg/dL); flags critical values."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "MetabolicInput",
            "type": "object",
            "required": ["glucose_mg_dl"],
            "properties": {
                "date": {"type": "string"},
                "glucose_mg_dl": {"type": "array", "items": {"type": "number"}, "minItems": 1},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        readings = payload.get("glucose_mg_dl", [])
        if not readings:
            raise ValueError("need at least one glucose reading")
        date = payload.get("date")
        s = summarize_glucose(readings)

        metric = {
            "id": "obs-metabolic-%s" % (date or "session"),
            "record_type": "Observation",
            "source_id": "metabolic",
            "title": "Glucose summary",
            "summary": "Mean %.0f mg/dL, %.0f%% in range (70-180), GMI %.1f%%." % (s["mean_mg_dl"], s["time_in_range_pct"], s["gmi_pct"]),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.9,
            "date": date,
            "tags": ["metabolic", "glucose"],
            "metadata": s,
            "observation_kind": "glucose_summary",
            "metric_name": "time_in_range_pct",
            "value": s["time_in_range_pct"],
            "unit": "%",
        }

        insights: List[Dict[str, Any]] = []
        # Critical value safety check (any single reading).
        critical = [v for v in readings if evidence.check_critical_lab("glucose", float(v))]
        if critical:
            insights.append({
                "id": "alert-metabolic-critical",
                "record_type": "PatternAlert",
                "source_id": "metabolic",
                "title": "Critical glucose value",
                "summary": "A glucose reading is in the critical range (%s mg/dL). Contact a clinician promptly; this is not interpreted here." % ", ".join("%.0f" % v for v in critical),
                "artifact_ids": [],
                "evidence_class": "safety-flag",
                "confidence": 0.0,
                "date": date,
                "tags": ["metabolic", "red-flag", "see-clinician"],
                "metadata": {"critical_mg_dl": critical},
                "relationship": "critical_value",
                "related_signals": ["glucose"],
                "evidence_count": len(critical),
                "suggested_validation": "Seek medical care. Do not wait for interpretation.",
            })
        elif s["time_in_range_pct"] < 70.0:
            conf = evidence.Confidence.C3
            txt = "Time-in-range is %.0f%% (target >70%%). Worth reviewing meals/timing." % s["time_in_range_pct"]
            insights.append({
                "id": "insight-metabolic-tir",
                "record_type": "InsightHypothesis",
                "source_id": "metabolic",
                "title": "Time-in-range",
                "summary": evidence.frame_statement(txt, conf),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(conf),
                "date": date,
                "tags": ["metabolic", "review-needed"],
                "metadata": s,
                "statement": txt,
                "evidence_record_ids": [metric["id"]],
                "open_questions": ["Which meals precede the highs?", "Discuss targets with a clinician."],
            })

        return ModuleResult(metrics=[metric], insights=insights)


register(MetabolicModule())
