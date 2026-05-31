"""Cycle module — menstrual cycle stats and cautious predictions.

From logged period-start dates we compute cycle lengths, a mean/spread, a next-
period prediction and a rough fertile-window estimate (calendar method, standard
~14-day luteal phase). This is NOT a contraception method and not a diagnosis —
predictions are explicitly low confidence and framed as estimates. Persistent
very short/long or highly irregular cycles raise a see-a-clinician prompt. Pure
stdlib.
"""

from datetime import date, timedelta
from typing import Any, Dict, List

from .base import ModuleResult, register
from .. import evidence


def _parse(d: str) -> date:
    return date.fromisoformat(d[:10])


def cycle_lengths(starts: List[str]) -> List[int]:
    ds = sorted(_parse(s) for s in starts)
    return [(ds[i + 1] - ds[i]).days for i in range(len(ds) - 1)]


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs)


def _spread(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


class CycleModule:
    id = "cycle"
    name = "Cycle — period stats, predictions, fertile-window estimate"
    domain = "cycle"
    summary = "Cycle length stats and a cautious next-period / fertile-window estimate (calendar method, not contraception)."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "CycleInput",
            "type": "object",
            "required": ["period_starts"],
            "properties": {
                "period_starts": {
                    "type": "array",
                    "items": {"type": "string", "description": "ISO date of a period's first day"},
                    "minItems": 1,
                },
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        starts = payload.get("period_starts", [])
        if not starts:
            raise ValueError("need at least one period start date")
        ds = sorted(_parse(s) for s in starts)
        lengths = cycle_lengths(starts)

        metrics: List[Dict[str, Any]] = []
        insights: List[Dict[str, Any]] = []
        notes: List[str] = []

        if not lengths:
            notes.append("only one period logged; need >=2 to estimate cycle length")
            return ModuleResult(metrics=metrics, insights=insights, notes=notes)

        mean_len = _mean([float(x) for x in lengths])
        spread = _spread([float(x) for x in lengths])
        last = ds[-1]
        next_period = last + timedelta(days=round(mean_len))
        ovulation = next_period - timedelta(days=14)
        fertile_start = ovulation - timedelta(days=5)
        fertile_end = ovulation + timedelta(days=1)

        metrics.append({
            "id": "obs-cycle-meanlen",
            "record_type": "Observation",
            "source_id": "cycle",
            "title": "Mean cycle length",
            "summary": "Mean %.1f d over %d cycle(s), spread +-%.1f d." % (mean_len, len(lengths), spread),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.9,
            "date": last.isoformat(),
            "tags": ["cycle"],
            "metadata": {"lengths_d": lengths, "mean_d": round(mean_len, 2), "spread_d": round(spread, 2)},
            "observation_kind": "cycle_length",
            "metric_name": "mean_cycle_length_d",
            "value": round(mean_len, 2),
            "unit": "days",
        })

        # Prediction confidence grows weakly with #cycles; never high. Few cycles
        # or large spread -> weak signal.
        base = evidence.Confidence.C3 if (len(lengths) >= 3 and spread <= 4) else evidence.Confidence.C2
        pred_text = (
            "Next period estimated around %s; fertile window roughly %s to %s. "
            "This is a calendar estimate, not contraception and not a diagnosis."
            % (next_period.isoformat(), fertile_start.isoformat(), fertile_end.isoformat())
        )
        insights.append({
            "id": "insight-cycle-prediction",
            "record_type": "InsightHypothesis",
            "source_id": "cycle",
            "title": "Next-period & fertile-window estimate",
            "summary": evidence.frame_statement(pred_text, base),
            "artifact_ids": [],
            "evidence_class": "derived-hypothesis",
            "confidence": evidence.confidence_to_numeric(base),
            "date": last.isoformat(),
            "tags": ["cycle", "prediction", "review-needed"],
            "metadata": {
                "next_period": next_period.isoformat(),
                "fertile_start": fertile_start.isoformat(),
                "fertile_end": fertile_end.isoformat(),
                "n_cycles": len(lengths),
            },
            "statement": pred_text,
            "evidence_record_ids": ["obs-cycle-meanlen"],
            "open_questions": ["Are your cycles usually regular?", "More logged cycles sharpen the estimate."],
        })

        # Cautious safety prompt for out-of-typical-range patterns.
        if mean_len < 21 or mean_len > 35 or spread > 7:
            insights.append({
                "id": "alert-cycle-irregular",
                "record_type": "PatternAlert",
                "source_id": "cycle",
                "title": "Cycle pattern worth discussing",
                "summary": (
                    "Your cycles look short/long or quite variable (mean %.0f d, spread +-%.0f d). "
                    "Often benign, but worth raising with a clinician — this is a prompt, not a diagnosis."
                    % (mean_len, spread)
                ),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(evidence.Confidence.C2),
                "date": last.isoformat(),
                "tags": ["cycle", "review-needed", "see-clinician"],
                "metadata": {"mean_d": round(mean_len, 1), "spread_d": round(spread, 1)},
                "relationship": "atypical_cycle",
                "related_signals": ["mean_cycle_length_d"],
                "evidence_count": len(lengths),
                "suggested_validation": "Track a few more cycles and review the pattern with a clinician.",
            })

        return ModuleResult(metrics=metrics, insights=insights, notes=notes)


register(CycleModule())
