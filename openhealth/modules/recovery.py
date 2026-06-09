"""Recovery module — versioned recovery / strain / sleep-debt scoring.

Turns the daily physiological signals OpenHealth already ingests (WHOOP HRV,
resting heart rate, sleep performance, day strain) into three transparent,
*versioned* scores:

- **recovery score** (0-100): a weighted blend of HRV (~70%), resting heart
  rate (~20%) and sleep (~10%), each normalized against the person's own recent
  baseline. HRV above baseline and RHR below baseline both push recovery up.
- **strain** (0-21): the cardiovascular load for the day, passed through from
  WHOOP's strain scale (validated to the 0-21 range) when available.
- **sleep debt** (hours): how far actual sleep fell short of a personal need.

Every metric carries an ``algo_version`` (e.g. ``recovery_score@v1``) in its
metadata so a hypothesis built on a score stays reproducible even after the
formula evolves — change the math, bump the version, old records stay labeled
with the version that produced them.

Why these weights: HRV is the most responsive autonomic signal day to day, so it
leads; resting HR is a slower, confirmatory signal; sleep performance rounds it
out. The exact split is a deliberate, documented choice, not a measurement, and
the whole computation is local and inspectable. Nothing here diagnoses. Pure
stdlib, zero external deps (core rule).
"""

from typing import Any, Dict, List, Optional

from .base import ModuleResult, register

# --- algorithm versions (bump on any formula change) -----------------------
ALGO_VERSIONS: Dict[str, str] = {
    "recovery_score": "recovery_score@v1",
    "strain": "strain@v1",
    "sleep_debt": "sleep_debt@v1",
}

# recovery_score@v1 component weights (must sum to 1.0).
RECOVERY_WEIGHTS: Dict[str, float] = {"hrv": 0.70, "rhr": 0.20, "sleep": 0.10}

# How far above/below baseline maps to the full 0-100 swing for HRV and RHR.
# +/-30% from baseline saturates the component. Documented, tunable, versioned.
_HRV_FULL_SWING = 0.30
_RHR_FULL_SWING = 0.30

STRAIN_MIN = 0.0
STRAIN_MAX = 21.0

DEFAULT_SLEEP_NEED_H = 8.0


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# --- component scorers (pure, unit-tested) ---------------------------------

def hrv_component(hrv_ms: float, baseline_hrv_ms: float) -> float:
    """0-100. 50 at baseline; rises as HRV exceeds baseline, falls below.

    Maps the relative deviation (hrv/baseline - 1) onto +/-50 around the midpoint,
    saturating at +/-_HRV_FULL_SWING.
    """
    if baseline_hrv_ms <= 0:
        raise ValueError("baseline HRV must be positive")
    rel = hrv_ms / baseline_hrv_ms - 1.0
    return _clamp(50.0 + 50.0 * (rel / _HRV_FULL_SWING), 0.0, 100.0)


def rhr_component(rhr_bpm: float, baseline_rhr_bpm: float) -> float:
    """0-100. 50 at baseline; rises as resting HR drops below baseline (better).

    Lower resting HR is better, so the deviation is inverted relative to HRV.
    """
    if baseline_rhr_bpm <= 0:
        raise ValueError("baseline resting HR must be positive")
    rel = rhr_bpm / baseline_rhr_bpm - 1.0
    return _clamp(50.0 - 50.0 * (rel / _RHR_FULL_SWING), 0.0, 100.0)


def sleep_component(sleep_performance_pct: float) -> float:
    """0-100. WHOOP sleep performance percentage is already on this scale."""
    return _clamp(float(sleep_performance_pct), 0.0, 100.0)


def recovery_score(
    hrv_ms: Optional[float],
    baseline_hrv_ms: Optional[float],
    rhr_bpm: Optional[float] = None,
    baseline_rhr_bpm: Optional[float] = None,
    sleep_performance_pct: Optional[float] = None,
) -> Dict[str, Any]:
    """Weighted recovery score (0-100) with a transparent component breakdown.

    Components with missing inputs are dropped and the remaining weights are
    renormalized, so a score is still produced from partial data (with a note).
    HRV is required — it is the anchor of the score.
    """
    if hrv_ms is None or baseline_hrv_ms is None:
        raise ValueError("HRV and its baseline are required for a recovery score")

    components: Dict[str, float] = {"hrv": hrv_component(hrv_ms, baseline_hrv_ms)}
    weights: Dict[str, float] = {"hrv": RECOVERY_WEIGHTS["hrv"]}

    if rhr_bpm is not None and baseline_rhr_bpm is not None:
        components["rhr"] = rhr_component(rhr_bpm, baseline_rhr_bpm)
        weights["rhr"] = RECOVERY_WEIGHTS["rhr"]
    if sleep_performance_pct is not None:
        components["sleep"] = sleep_component(sleep_performance_pct)
        weights["sleep"] = RECOVERY_WEIGHTS["sleep"]

    total_w = sum(weights.values())
    score = sum(components[k] * weights[k] for k in components) / total_w

    return {
        "score": round(score, 1),
        "components": {k: round(v, 1) for k, v in components.items()},
        "weights_used": {k: round(weights[k] / total_w, 4) for k in weights},
        "missing": [k for k in RECOVERY_WEIGHTS if k not in components],
        "algo_version": ALGO_VERSIONS["recovery_score"],
    }


def normalize_strain(raw_strain: float) -> Dict[str, Any]:
    """Validate and pass through a WHOOP-scale strain value (0-21)."""
    s = _clamp(float(raw_strain), STRAIN_MIN, STRAIN_MAX)
    return {
        "strain": round(s, 2),
        "scale": "0-21",
        "clamped": s != float(raw_strain),
        "algo_version": ALGO_VERSIONS["strain"],
    }


def sleep_debt(actual_sleep_h: float, need_h: float = DEFAULT_SLEEP_NEED_H) -> Dict[str, Any]:
    """Sleep debt in hours = max(0, need - actual). Surplus reported separately."""
    deficit = max(0.0, need_h - float(actual_sleep_h))
    return {
        "sleep_debt_h": round(deficit, 2),
        "actual_sleep_h": round(float(actual_sleep_h), 2),
        "need_h": round(float(need_h), 2),
        "surplus_h": round(max(0.0, float(actual_sleep_h) - need_h), 2),
        "algo_version": ALGO_VERSIONS["sleep_debt"],
    }


# --- index reader: build a payload from indexed WHOOP records --------------

def _latest_metric_value(records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str) -> Optional[float]:
    """Most-recent value (on or before ``day``) of a WHOOP metric."""
    hits = [
        r for r in records
        if r.get("observation_kind") == obs_kind
        and r.get("metric_name") == metric_name
        and r.get("date") and r["date"] <= day
        and r.get("value") is not None
    ]
    if not hits:
        return None
    hits.sort(key=lambda r: r["date"])
    return float(hits[-1]["value"])


def _baseline_mean(
    records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str, window_days: int
) -> Optional[float]:
    """Mean of a WHOOP metric over the ``window_days`` ending at ``day``."""
    from datetime import date as _d

    end = _d.fromisoformat(day)
    vals: List[float] = []
    for r in records:
        if r.get("observation_kind") != obs_kind or r.get("metric_name") != metric_name:
            continue
        d = r.get("date")
        v = r.get("value")
        if not d or v is None:
            continue
        try:
            rd = _d.fromisoformat(d)
        except ValueError:
            continue
        delta = (end - rd).days
        if 0 <= delta < window_days:
            vals.append(float(v))
    if not vals:
        return None
    return sum(vals) / len(vals)


def from_index(
    db_path,
    day: str,
    baseline_window_days: int = 60,
    sleep_need_h: float = DEFAULT_SLEEP_NEED_H,
) -> Dict[str, Any]:
    """Assemble a recovery-module payload for ``day`` from indexed WHOOP records.

    Reads only through the index API (never the raw files). Returns a payload
    dict ready for ``RecoveryModule.compute``; raises if no HRV is available.
    """
    from .. import index

    records = index.list_records(db_path, "Observation")

    hrv = _latest_metric_value(records, "whoop_recovery_metric", "hrv_rmssd", day)
    baseline_hrv = _baseline_mean(records, "whoop_recovery_metric", "hrv_rmssd", day, baseline_window_days)
    rhr = _latest_metric_value(records, "whoop_recovery_metric", "resting_heart_rate", day)
    baseline_rhr = _baseline_mean(records, "whoop_recovery_metric", "resting_heart_rate", day, baseline_window_days)
    sleep_perf = _latest_metric_value(records, "whoop_sleep_metric", "sleep_performance_percentage", day)
    strain = _latest_metric_value(records, "whoop_cycle_metric", "strain", day)

    sleep_ms = _latest_metric_value(records, "whoop_sleep_metric", "total_in_bed_time_milli", day)
    awake_ms = _latest_metric_value(records, "whoop_sleep_metric", "total_awake_time_milli", day)
    actual_sleep_h = None
    if sleep_ms is not None:
        asleep_ms = sleep_ms - (awake_ms or 0.0)
        actual_sleep_h = asleep_ms / 3_600_000.0

    return {
        "date": day,
        "hrv_ms": hrv,
        "baseline_hrv_ms": baseline_hrv,
        "rhr_bpm": rhr,
        "baseline_rhr_bpm": baseline_rhr,
        "sleep_performance_pct": sleep_perf,
        "strain": strain,
        "actual_sleep_h": actual_sleep_h,
        "sleep_need_h": sleep_need_h,
        "baseline_window_days": baseline_window_days,
    }


# --- module ----------------------------------------------------------------

class RecoveryModule:
    id = "recovery"
    name = "Recovery — versioned recovery, strain & sleep debt"
    domain = "recovery"
    summary = "Computes a versioned recovery score (HRV/RHR/sleep), passes through strain (0-21), and sleep debt."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "RecoveryInput",
            "type": "object",
            "required": ["hrv_ms", "baseline_hrv_ms"],
            "properties": {
                "date": {"type": "string"},
                "hrv_ms": {"type": "number", "description": "Day's HRV (RMSSD, ms)"},
                "baseline_hrv_ms": {"type": "number", "description": "Personal baseline HRV (ms)"},
                "rhr_bpm": {"type": "number"},
                "baseline_rhr_bpm": {"type": "number"},
                "sleep_performance_pct": {"type": "number"},
                "strain": {"type": "number", "description": "Day strain on WHOOP's 0-21 scale"},
                "actual_sleep_h": {"type": "number"},
                "sleep_need_h": {"type": "number", "default": DEFAULT_SLEEP_NEED_H},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        day = payload.get("date")
        rec = recovery_score(
            hrv_ms=payload.get("hrv_ms"),
            baseline_hrv_ms=payload.get("baseline_hrv_ms"),
            rhr_bpm=payload.get("rhr_bpm"),
            baseline_rhr_bpm=payload.get("baseline_rhr_bpm"),
            sleep_performance_pct=payload.get("sleep_performance_pct"),
        )

        metrics: List[Dict[str, Any]] = [{
            "id": "obs-recovery-score-%s" % (day or "session"),
            "record_type": "Observation",
            "source_id": "recovery",
            "title": "Recovery score",
            "summary": "Recovery %.0f/100 (HRV-led blend) on %s." % (rec["score"], day or "session"),
            "artifact_ids": [],
            "evidence_class": "derived-metric",
            "confidence": 0.9,
            "date": day,
            "tags": ["recovery", "score"],
            "metadata": rec,
            "observation_kind": "recovery_score",
            "metric_name": "recovery_score",
            "value": rec["score"],
            "unit": "score_0_100",
        }]

        notes: List[str] = ["recovery_score uses %s" % rec["algo_version"]]
        if rec["missing"]:
            notes.append("partial inputs; missing components: %s" % ", ".join(rec["missing"]))

        strain_raw = payload.get("strain")
        if strain_raw is not None:
            st = normalize_strain(strain_raw)
            metrics.append({
                "id": "obs-recovery-strain-%s" % (day or "session"),
                "record_type": "Observation",
                "source_id": "recovery",
                "title": "Day strain",
                "summary": "Strain %.1f/21 on %s." % (st["strain"], day or "session"),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.9,
                "date": day,
                "tags": ["recovery", "strain"],
                "metadata": st,
                "observation_kind": "strain",
                "metric_name": "strain",
                "value": st["strain"],
                "unit": "strain_0_21",
            })

        actual_sleep_h = payload.get("actual_sleep_h")
        if actual_sleep_h is not None:
            sd = sleep_debt(actual_sleep_h, payload.get("sleep_need_h", DEFAULT_SLEEP_NEED_H))
            metrics.append({
                "id": "obs-recovery-sleepdebt-%s" % (day or "session"),
                "record_type": "Observation",
                "source_id": "recovery",
                "title": "Sleep debt",
                "summary": "Sleep debt %.1f h (slept %.1f of %.1f h need) on %s."
                % (sd["sleep_debt_h"], sd["actual_sleep_h"], sd["need_h"], day or "session"),
                "artifact_ids": [],
                "evidence_class": "derived-metric",
                "confidence": 0.9,
                "date": day,
                "tags": ["recovery", "sleep-debt"],
                "metadata": sd,
                "observation_kind": "sleep_debt",
                "metric_name": "sleep_debt_h",
                "value": sd["sleep_debt_h"],
                "unit": "h",
            })

        return ModuleResult(metrics=metrics, insights=[], notes=notes)


def persist(result: ModuleResult, db_path) -> int:
    """Write recovery metrics into the SQLite index. Returns count written."""
    from .. import index

    written = 0
    for rec in list(result.metrics) + list(result.insights):
        index.upsert_record(db_path, rec)
        written += 1
    return written


register(RecoveryModule())
