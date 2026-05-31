"""Pulse module — heart-rate variability, resting HR, a cautious readiness read.

Original implementation of standard HRV measures (Task Force 1996 definitions),
pure stdlib. Time-domain measures are exact and golden-tested. A lightweight
frequency-domain estimate (LF/HF) is computed from a linearly-interpolated RR
tachogram via a naive DFT — good enough to surface a trend, explicitly low
confidence, refine later (see good-first task `pulse-freq-welch`).

Nothing here diagnoses. Personal readings are capped at C3 and framed as
prompts, per openhealth.evidence.
"""

import cmath
import math
from typing import Any, Dict, List, Optional

from .base import HealthModule, ModuleResult, register
from .. import evidence


# --- time-domain HRV (exact, golden-tested) -------------------------------

def _clean_rr(rr: List[Any]) -> List[float]:
    """Keep positive, physiologically plausible RR intervals in milliseconds.

    Plausible adult range ~ 300-2000 ms (30-200 bpm). Drops obvious artifacts.
    """
    out: List[float] = []
    for x in rr:
        try:
            v = float(x)
        except (TypeError, ValueError):
            continue
        if 300.0 <= v <= 2000.0:
            out.append(v)
    return out


def mean_rr(rr: List[float]) -> float:
    return sum(rr) / len(rr)


def mean_hr_bpm(rr: List[float]) -> float:
    """Mean heart rate from mean RR interval (ms)."""
    return 60000.0 / mean_rr(rr)


def sdnn(rr: List[float]) -> float:
    """Standard deviation of NN intervals (sample SD, ddof=1)."""
    n = len(rr)
    m = mean_rr(rr)
    var = sum((x - m) ** 2 for x in rr) / (n - 1)
    return math.sqrt(var)


def rmssd(rr: List[float]) -> float:
    """Root mean square of successive differences."""
    diffs = [rr[i + 1] - rr[i] for i in range(len(rr) - 1)]
    return math.sqrt(sum(d * d for d in diffs) / len(diffs))


def pnn50(rr: List[float]) -> float:
    """Percentage of successive RR differences greater than 50 ms."""
    diffs = [abs(rr[i + 1] - rr[i]) for i in range(len(rr) - 1)]
    return 100.0 * sum(1 for d in diffs if d > 50.0) / len(diffs)


# --- frequency-domain (best-effort, low confidence) -----------------------

def _interpolate_tachogram(rr: List[float], fs: float = 4.0) -> List[float]:
    """Resample the RR tachogram onto an even grid at `fs` Hz via linear interp.

    Time axis is the cumulative sum of RR (seconds). Returns evenly-spaced RR
    values (ms) suitable for a DFT.
    """
    t = [0.0]
    for v in rr:
        t.append(t[-1] + v / 1000.0)
    t = t[1:]  # time of each beat (s)
    if t[-1] <= 0:
        return []
    n = int(t[-1] * fs)
    if n < 4:
        return []
    grid = [i / fs for i in range(n)]
    out: List[float] = []
    j = 0
    for g in grid:
        while j < len(t) - 1 and t[j + 1] < g:
            j += 1
        if j >= len(t) - 1:
            out.append(rr[-1])
            continue
        t0, t1 = t[j], t[j + 1]
        v0, v1 = rr[j], rr[j + 1]
        frac = 0.0 if t1 == t0 else (g - t0) / (t1 - t0)
        out.append(v0 + (v1 - v0) * frac)
    return out


def _band_power(series: List[float], fs: float, lo: float, hi: float) -> float:
    """Naive DFT power in [lo, hi) Hz. O(n^2) — fine for short HRV windows."""
    n = len(series)
    if n == 0:
        return 0.0
    mean = sum(series) / n
    centered = [v - mean for v in series]
    power = 0.0
    # Only need frequency bins inside the band.
    k_lo = max(1, int(math.floor(lo * n / fs)))
    k_hi = min(n // 2, int(math.ceil(hi * n / fs)))
    for k in range(k_lo, k_hi + 1):
        acc = 0j
        ang = -2j * math.pi * k / n
        for idx, v in enumerate(centered):
            acc += v * cmath.exp(ang * idx)
        power += (abs(acc) ** 2) / n
    return power


def freq_domain(rr: List[float]) -> Dict[str, float]:
    """LF (0.04-0.15 Hz), HF (0.15-0.40 Hz) power and LF/HF ratio (ms^2-ish)."""
    series = _interpolate_tachogram(rr)
    if len(series) < 8:
        return {"lf": 0.0, "hf": 0.0, "lf_hf": 0.0, "total_power": 0.0}
    fs = 4.0
    lf = _band_power(series, fs, 0.04, 0.15)
    hf = _band_power(series, fs, 0.15, 0.40)
    total = _band_power(series, fs, 0.0033, 0.40)
    return {
        "lf": round(lf, 3),
        "hf": round(hf, 3),
        "lf_hf": round(lf / hf, 3) if hf > 0 else 0.0,
        "total_power": round(total, 3),
    }


def hrv_summary(rr_intervals: List[Any]) -> Dict[str, Any]:
    """Full HRV summary from RR intervals (ms). Raises if too few clean beats."""
    rr = _clean_rr(rr_intervals)
    if len(rr) < 2:
        raise ValueError("need at least 2 clean RR intervals")
    summary: Dict[str, Any] = {
        "n_beats": len(rr),
        "mean_hr_bpm": round(mean_hr_bpm(rr), 2),
        "mean_rr_ms": round(mean_rr(rr), 2),
        "sdnn_ms": round(sdnn(rr), 3),
        "rmssd_ms": round(rmssd(rr), 3),
        "pnn50_pct": round(pnn50(rr), 3),
    }
    summary.update(freq_domain(rr))
    return summary


# --- module ---------------------------------------------------------------

class PulseModule:
    id = "pulse"
    name = "Pulse — HRV, resting heart rate & readiness"
    domain = "pulse"
    summary = "Turns RR-interval / heart-beat data into HRV metrics and a cautious readiness prompt."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "PulseInput",
            "type": "object",
            "required": ["rr_intervals_ms"],
            "properties": {
                "date": {"type": "string", "description": "ISO date of the reading"},
                "rr_intervals_ms": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "description": "Beat-to-beat RR intervals in milliseconds",
                },
                "baseline_rmssd_ms": {
                    "type": "number",
                    "description": "Optional personal baseline RMSSD for a relative readiness read",
                },
                "source": {"type": "string"},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        rr = payload.get("rr_intervals_ms", [])
        date = payload.get("date")
        summary = hrv_summary(rr)

        metric = {
            "id": "obs-pulse-%s" % (date or "session"),
            "record_type": "Observation",
            "source_id": payload.get("source", "pulse"),
            "title": "HRV reading",
            "summary": "RMSSD %.1f ms, mean HR %.0f bpm over %d beats."
            % (summary["rmssd_ms"], summary["mean_hr_bpm"], summary["n_beats"]),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.9,
            "date": date,
            "tags": ["pulse", "hrv"],
            "metadata": summary,
            "observation_kind": "hrv",
            "metric_name": "rmssd_ms",
            "value": summary["rmssd_ms"],
            "unit": "ms",
        }

        insights: List[Dict[str, Any]] = []
        baseline = payload.get("baseline_rmssd_ms")
        if baseline:
            ratio = summary["rmssd_ms"] / float(baseline)
            if ratio >= 0.9:
                read = "HRV is around your usual baseline — a normal day."
            elif ratio >= 0.7:
                read = "HRV is a bit below your baseline. An easier day may feel better — worth noting, not alarming."
            else:
                read = "HRV is well below your baseline today. Common after poor sleep, alcohol or illness; consider lighter activity."
            # Personal single-day reading: capped at C2 until validated (n-of-1).
            conf = evidence.cap_personal_pattern(evidence.Confidence.C3, validated_switches=0)
            insights.append({
                "id": "insight-pulse-%s" % (date or "session"),
                "record_type": "InsightHypothesis",
                "source_id": "pulse",
                "title": "Today's readiness",
                "summary": evidence.frame_statement(read, conf),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(conf),
                "date": date,
                "tags": ["pulse", "readiness", "review-needed"],
                "metadata": {"baseline_rmssd_ms": baseline, "ratio": round(ratio, 3)},
                "statement": read,
                "evidence_record_ids": [metric["id"]],
                "open_questions": [
                    "How was last night's sleep?",
                    "Any alcohol, late meal, or stress yesterday?",
                ],
            })

        return ModuleResult(metrics=[metric], insights=insights)


register(PulseModule())
