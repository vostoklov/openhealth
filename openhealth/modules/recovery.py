"""Recovery module — versioned recovery / strain / sleep-debt scoring.

Turns the daily physiological signals OpenHealth already ingests (WHOOP HRV,
resting heart rate, respiratory rate, sleep performance, day strain) into
transparent, *versioned* scores:

- **recovery score** (0-100): a weighted blend of HRV (~60-70%), resting heart
  rate (~20%) and, when available, respiratory rate (~15%) and sleep (~10%),
  each normalized against the person's own recent baseline. HRV above baseline
  and RHR below baseline both push recovery up; respiratory rate deviating from
  baseline (in either direction) pulls it down, because a respiratory-rate
  shift is a known early marker of illness / stress / overtraining (WHOOP added
  it to recovery for exactly this reason).
- **strain** (0-21): the cardiovascular load for the day, passed through from
  WHOOP's strain scale when available.
- **sleep debt** (hours): how far actual sleep fell short of a *personal* need,
  optionally accumulated across a rolling window of recent nights rather than a
  single night against a fixed constant.

Every metric carries an ``algo_version`` (e.g. ``recovery_score@v3``) in its
metadata so a hypothesis built on a score stays reproducible even after the
formula evolves — change the math, bump the version, old records stay labeled
with the version that produced them.

HRV scoring (recovery_score@v3): rMSSD is log-normally distributed (a long
right tail), so we score and baseline on ``ln(rMSSD)`` rather than raw ms, and
normalize the deviation by the *spread* (standard deviation) of the person's
own recent ln(rMSSD) instead of a fixed ±30% threshold. This is the
Altini / HRV4Training convention: in ln-space equal millisecond moves at low
and high HRV become comparable, and a baseline of mean ± SD gives an honest,
personal "normal range" (smallest-worthwhile-change logic) instead of magic
0.9 / 0.7 cutoffs.

C-grade caveats (kept honest):
- We consume the provider's already-aggregated *nightly* rMSSD as-is. WHOOP's
  exact nightly-rMSSD aggregation window is publicly ambiguous ("deepest sleep"
  vs "weighted average across the night"); the ln/SD work here applies to
  *scoring and baselining*, not to re-aggregating raw RR.
- The component weights are a deliberate, documented choice, not a measurement,
  and the whole computation is local and inspectable. Nothing here diagnoses.

Pure stdlib, zero external deps (core rule).
"""

import math
from statistics import pstdev
from typing import Any, Dict, List, Optional

from .base import ModuleResult, register

# --- algorithm versions (bump on any formula change) -----------------------
ALGO_VERSIONS: Dict[str, str] = {
    "recovery_score": "recovery_score@v3",
    "strain": "strain@v1",
    "sleep_debt": "sleep_debt@v2",
}

# recovery_score@v3 component weights (renormalized over present components).
# Respiratory rate sits between RHR and sleep; sleep rounds it out. Public WHOOP
# ballpark is HRV-dominant + RHR + respiratory rate; the split is our open,
# versioned choice, not a claim of WHOOP parity.
RECOVERY_WEIGHTS: Dict[str, float] = {
    "hrv": 0.60,
    "rhr": 0.20,
    "respiratory": 0.15,
    "sleep": 0.05,
}

# RHR component: how far below/above baseline maps to the full 0-100 swing.
# +/-30% from baseline saturates the component. Documented, tunable, versioned.
_RHR_FULL_SWING = 0.30

# HRV component (ln-rMSSD, v3): the deviation of today's ln(rMSSD) from the
# baseline ln(rMSSD) is expressed in standard deviations of the person's own
# recent ln(rMSSD), then mapped onto +/-50 around the midpoint. _HRV_FULL_SWING_SD
# standard deviations saturate the component. ~2 SD is the conventional
# "normal range" edge, so 2 SD below baseline -> 0, 2 SD above -> 100.
_HRV_FULL_SWING_SD = 2.0

# Fallback ln-SD when the baseline window is too short to estimate a personal
# spread (need >= 2 samples). Typical within-person ln(rMSSD) SD is ~0.10-0.20;
# 0.15 is a conservative default. Flagged in metadata when used.
_HRV_DEFAULT_LN_SD = 0.15

# Respiratory rate component: deviation from baseline (in either direction) is a
# penalty. A shift of _RESP_DEADBAND breaths/min is ignored (normal night-to-
# night noise); beyond that the component drops, reaching 0 at _RESP_FULL_SWING.
_RESP_DEADBAND = 1.0          # breaths/min: WHOOP's own "meaningful shift" floor
_RESP_FULL_SWING = 3.0        # breaths/min above the deadband -> component at 0

STRAIN_MIN = 0.0
STRAIN_MAX = 21.0

# Baseline windows (days). Recovery baselines use the medium window; a short
# window is available for day-to-day "normal range" reads. 60d proved too
# inert; ~28d tracks the person while staying stable (Altini/WHOOP ballpark).
DEFAULT_BASELINE_WINDOW_DAYS = 28
SHORT_BASELINE_WINDOW_DAYS = 7

DEFAULT_SLEEP_NEED_H = 8.0
# Sleep-debt accumulation window (nights). WHOOP-style debt is multi-night, not
# a single night vs a constant.
DEFAULT_SLEEP_DEBT_WINDOW_NIGHTS = 14


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


# --- component scorers (pure, unit-tested) ---------------------------------

def hrv_component(
    hrv_ms: float,
    baseline_hrv_ms: float,
    baseline_ln_sd: Optional[float] = None,
) -> float:
    """0-100. 50 at baseline; rises as HRV exceeds baseline, falls below.

    recovery_score@v3 scores on ``ln(rMSSD)``. The deviation of today's
    ln(rMSSD) from the baseline ln(rMSSD) is divided by the spread (SD) of the
    person's own recent ln(rMSSD) and mapped onto +/-50 around the midpoint,
    saturating at +/-_HRV_FULL_SWING_SD standard deviations.

    ``baseline_hrv_ms`` is the geometric-style baseline expressed in ms (i.e.
    ``exp(mean(ln rMSSD))``); both inputs are ln-transformed here. When the
    personal ln-SD is unknown (too few baseline samples) a conservative default
    spread is used (see ``_HRV_DEFAULT_LN_SD``).
    """
    if hrv_ms <= 0:
        raise ValueError("HRV must be positive (ln scale)")
    if baseline_hrv_ms <= 0:
        raise ValueError("baseline HRV must be positive (ln scale)")
    ln_sd = baseline_ln_sd if (baseline_ln_sd and baseline_ln_sd > 0) else _HRV_DEFAULT_LN_SD
    ln_dev = math.log(hrv_ms) - math.log(baseline_hrv_ms)
    z = ln_dev / ln_sd  # deviation in personal standard deviations
    return _clamp(50.0 + 50.0 * (z / _HRV_FULL_SWING_SD), 0.0, 100.0)


def rhr_component(rhr_bpm: float, baseline_rhr_bpm: float) -> float:
    """0-100. 50 at baseline; rises as resting HR drops below baseline (better).

    Lower resting HR is better, so the deviation is inverted relative to HRV.
    """
    if baseline_rhr_bpm <= 0:
        raise ValueError("baseline resting HR must be positive")
    rel = rhr_bpm / baseline_rhr_bpm - 1.0
    return _clamp(50.0 - 50.0 * (rel / _RHR_FULL_SWING), 0.0, 100.0)


def respiratory_component(resp_rate: float, baseline_resp_rate: float) -> float:
    """0-100. 100 at/near baseline; drops as respiratory rate deviates either way.

    A respiratory-rate shift from one's baseline (up *or* down) is an early
    marker of illness / stress / overtraining, so any deviation is a penalty.
    Deviations within ``_RESP_DEADBAND`` breaths/min are treated as noise (full
    100); beyond that the component falls linearly to 0 at ``_RESP_FULL_SWING``
    breaths/min past the deadband.
    """
    if baseline_resp_rate <= 0:
        raise ValueError("baseline respiratory rate must be positive")
    dev = abs(float(resp_rate) - float(baseline_resp_rate))
    excess = max(0.0, dev - _RESP_DEADBAND)
    return _clamp(100.0 - 100.0 * (excess / _RESP_FULL_SWING), 0.0, 100.0)


def sleep_component(sleep_performance_pct: float) -> float:
    """0-100. WHOOP sleep performance percentage is already on this scale."""
    return _clamp(float(sleep_performance_pct), 0.0, 100.0)


def recovery_score(
    hrv_ms: Optional[float],
    baseline_hrv_ms: Optional[float],
    rhr_bpm: Optional[float] = None,
    baseline_rhr_bpm: Optional[float] = None,
    sleep_performance_pct: Optional[float] = None,
    respiratory_rate: Optional[float] = None,
    baseline_respiratory_rate: Optional[float] = None,
    baseline_hrv_ln_sd: Optional[float] = None,
) -> Dict[str, Any]:
    """Weighted recovery score (0-100) with a transparent component breakdown.

    Components with missing inputs are dropped and the remaining weights are
    renormalized, so a score is still produced from partial data (with a note).
    HRV is required — it is the anchor of the score.

    recovery_score@v3: HRV is scored on ln(rMSSD) normalized by the person's own
    ln-SD (``method: "ln_rmssd_sd"``); respiratory rate is an optional penalty
    component when both today's value and a baseline are present.
    """
    if hrv_ms is None or baseline_hrv_ms is None:
        raise ValueError("HRV and its baseline are required for a recovery score")

    components: Dict[str, float] = {
        "hrv": hrv_component(hrv_ms, baseline_hrv_ms, baseline_hrv_ln_sd)
    }
    weights: Dict[str, float] = {"hrv": RECOVERY_WEIGHTS["hrv"]}

    if rhr_bpm is not None and baseline_rhr_bpm is not None:
        components["rhr"] = rhr_component(rhr_bpm, baseline_rhr_bpm)
        weights["rhr"] = RECOVERY_WEIGHTS["rhr"]
    if respiratory_rate is not None and baseline_respiratory_rate is not None:
        components["respiratory"] = respiratory_component(respiratory_rate, baseline_respiratory_rate)
        weights["respiratory"] = RECOVERY_WEIGHTS["respiratory"]
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
        "method": "ln_rmssd_sd",
        "hrv_ln_sd_used": round(
            baseline_hrv_ln_sd if (baseline_hrv_ln_sd and baseline_hrv_ln_sd > 0) else _HRV_DEFAULT_LN_SD,
            4,
        ),
        "hrv_ln_sd_is_default": not (baseline_hrv_ln_sd and baseline_hrv_ln_sd > 0),
        "algo_version": ALGO_VERSIONS["recovery_score"],
    }


def normalize_strain(raw_strain: float) -> Dict[str, Any]:
    """Validate and pass through a WHOOP-scale strain value (0-21).

    NOTE (C-grade): WHOOP strain is a *logarithmic*, Borg-RPE-derived 0-21 scale
    (Borg ~ HR/10), not linear — it takes more load to move 16->17 than 4->5.
    We pass the provider's value through unchanged and only clamp to range; we
    do not re-derive it. For sources without a WHOOP strain (Apple/Garmin) no
    strain is produced here.
    """
    s = _clamp(float(raw_strain), STRAIN_MIN, STRAIN_MAX)
    return {
        "strain": round(s, 2),
        "scale": "0-21",
        "scale_note": "logarithmic (Borg-RPE-derived); passthrough from provider",
        "clamped": s != float(raw_strain),
        "algo_version": ALGO_VERSIONS["strain"],
    }


def sleep_debt(
    actual_sleep_h: float,
    need_h: float = DEFAULT_SLEEP_NEED_H,
    recent_nights_h: Optional[List[float]] = None,
    window_nights: int = DEFAULT_SLEEP_DEBT_WINDOW_NIGHTS,
) -> Dict[str, Any]:
    """Sleep debt in hours, single-night and (optionally) accumulated.

    ``sleep_debt_h`` is the single-night shortfall ``max(0, need - actual)`` so
    callers and existing series keep working.

    sleep_debt@v2: when ``recent_nights_h`` is supplied (most-recent-last), the
    debt is *accumulated* over the trailing ``window_nights`` nights — the sum
    of per-night shortfalls against ``need_h`` — rather than a single night
    against a constant. This is the WHOOP/Rise multi-night view: a few short
    nights add up. ``accumulated_debt_h`` carries that rolling figure;
    ``sleep_need_h`` is personal/configurable (default 8.0h).

    Sleep need is an *estimate*, not a measurement (C2). Accumulated debt is a
    derived figure over the chosen window, also C2.
    """
    actual = float(actual_sleep_h)
    deficit = max(0.0, need_h - actual)
    out: Dict[str, Any] = {
        "sleep_debt_h": round(deficit, 2),
        "actual_sleep_h": round(actual, 2),
        "need_h": round(float(need_h), 2),
        "surplus_h": round(max(0.0, actual - need_h), 2),
        "algo_version": ALGO_VERSIONS["sleep_debt"],
    }

    if recent_nights_h:
        window = [float(h) for h in recent_nights_h][-int(window_nights):]
        accumulated = sum(max(0.0, need_h - h) for h in window)
        out["accumulated_debt_h"] = round(accumulated, 2)
        out["debt_window_nights"] = len(window)
        out["debt_window_target_nights"] = int(window_nights)

    return out


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


def _window_values(
    records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str, window_days: int
) -> List[float]:
    """Values of a WHOOP metric over the ``window_days`` ending at ``day``."""
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
    return vals


def _baseline_mean(
    records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str, window_days: int
) -> Optional[float]:
    """Arithmetic mean of a WHOOP metric over the window (used for RHR / resp)."""
    vals = _window_values(records, obs_kind, metric_name, day, window_days)
    if not vals:
        return None
    return sum(vals) / len(vals)


def _baseline_geomean_and_lnsd(
    records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str, window_days: int
) -> tuple:
    """Geometric-mean baseline (ms) and ln-SD of a positive metric over the window.

    Returns ``(baseline_ms, ln_sd)`` where ``baseline_ms = exp(mean(ln v))`` and
    ``ln_sd`` is the population SD of ``ln v`` (None when < 2 positive samples).
    Used for HRV so the baseline and spread live in ln-space (recovery@v3).
    """
    vals = [v for v in _window_values(records, obs_kind, metric_name, day, window_days) if v > 0]
    if not vals:
        return (None, None)
    lns = [math.log(v) for v in vals]
    baseline_ms = math.exp(sum(lns) / len(lns))
    ln_sd = pstdev(lns) if len(lns) >= 2 else None
    return (baseline_ms, ln_sd)


def _nightly_sleep_hours(records: List[Dict[str, Any]], day: str, window_days: int) -> List[float]:
    """Per-night asleep hours over the window ending at ``day`` (most-recent-last).

    Derived from total-in-bed minus total-awake when available; falls back to
    sleep_performance_percentage * need when duration is absent (low confidence
    in the caller's hands).
    """
    from datetime import date as _d

    end = _d.fromisoformat(day)
    in_bed: Dict[str, float] = {}
    awake: Dict[str, float] = {}
    for r in records:
        if r.get("observation_kind") != "whoop_sleep_metric":
            continue
        d = r.get("date")
        v = r.get("value")
        if not d or v is None:
            continue
        try:
            rd = _d.fromisoformat(d)
        except ValueError:
            continue
        if not (0 <= (end - rd).days < window_days):
            continue
        if r.get("metric_name") == "total_in_bed_time_milli":
            in_bed[d] = float(v)
        elif r.get("metric_name") == "total_awake_time_milli":
            awake[d] = float(v)

    nights: List[tuple] = []
    for d, bed_ms in in_bed.items():
        asleep_ms = bed_ms - awake.get(d, 0.0)
        nights.append((d, asleep_ms / 3_600_000.0))
    nights.sort(key=lambda x: x[0])
    return [h for _, h in nights]


def from_index(
    db_path,
    day: str,
    baseline_window_days: int = DEFAULT_BASELINE_WINDOW_DAYS,
    sleep_need_h: float = DEFAULT_SLEEP_NEED_H,
    sleep_debt_window_nights: int = DEFAULT_SLEEP_DEBT_WINDOW_NIGHTS,
) -> Dict[str, Any]:
    """Assemble a recovery-module payload for ``day`` from indexed WHOOP records.

    Reads only through the index API (never the raw files). Returns a payload
    dict ready for ``RecoveryModule.compute``; raises if no HRV is available.

    ``baseline_window_days`` defaults to ~28d (was 60d) — configurable per call,
    backward-compatible. HRV baseline + ln-SD are computed in ln-space.
    """
    from .. import index

    records = index.list_records(db_path, "Observation")

    hrv = _latest_metric_value(records, "whoop_recovery_metric", "hrv_rmssd", day)
    baseline_hrv, baseline_hrv_ln_sd = _baseline_geomean_and_lnsd(
        records, "whoop_recovery_metric", "hrv_rmssd", day, baseline_window_days
    )
    rhr = _latest_metric_value(records, "whoop_recovery_metric", "resting_heart_rate", day)
    baseline_rhr = _baseline_mean(records, "whoop_recovery_metric", "resting_heart_rate", day, baseline_window_days)
    resp = _latest_metric_value(records, "whoop_sleep_metric", "respiratory_rate", day)
    baseline_resp = _baseline_mean(records, "whoop_sleep_metric", "respiratory_rate", day, baseline_window_days)
    sleep_perf = _latest_metric_value(records, "whoop_sleep_metric", "sleep_performance_percentage", day)
    strain = _latest_metric_value(records, "whoop_cycle_metric", "strain", day)

    sleep_ms = _latest_metric_value(records, "whoop_sleep_metric", "total_in_bed_time_milli", day)
    awake_ms = _latest_metric_value(records, "whoop_sleep_metric", "total_awake_time_milli", day)
    actual_sleep_h = None
    if sleep_ms is not None:
        asleep_ms = sleep_ms - (awake_ms or 0.0)
        actual_sleep_h = asleep_ms / 3_600_000.0

    recent_nights_h = _nightly_sleep_hours(records, day, sleep_debt_window_nights)

    return {
        "date": day,
        "hrv_ms": hrv,
        "baseline_hrv_ms": baseline_hrv,
        "baseline_hrv_ln_sd": baseline_hrv_ln_sd,
        "rhr_bpm": rhr,
        "baseline_rhr_bpm": baseline_rhr,
        "respiratory_rate": resp,
        "baseline_respiratory_rate": baseline_resp,
        "sleep_performance_pct": sleep_perf,
        "strain": strain,
        "actual_sleep_h": actual_sleep_h,
        "recent_nights_h": recent_nights_h or None,
        "sleep_need_h": sleep_need_h,
        "sleep_debt_window_nights": sleep_debt_window_nights,
        "baseline_window_days": baseline_window_days,
    }


# --- module ----------------------------------------------------------------

class RecoveryModule:
    id = "recovery"
    name = "Recovery — versioned recovery, strain & sleep debt"
    domain = "recovery"
    summary = (
        "Computes a versioned recovery score (HRV/RHR/respiratory/sleep), "
        "passes through strain (0-21), and sleep debt."
    )

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "RecoveryInput",
            "type": "object",
            "required": ["hrv_ms", "baseline_hrv_ms"],
            "properties": {
                "date": {"type": "string"},
                "hrv_ms": {"type": "number", "description": "Day's HRV (RMSSD, ms)"},
                "baseline_hrv_ms": {
                    "type": "number",
                    "description": "Personal baseline HRV (ms; geometric mean of ln rMSSD)",
                },
                "baseline_hrv_ln_sd": {
                    "type": "number",
                    "description": "SD of personal ln(rMSSD) over the baseline window",
                },
                "rhr_bpm": {"type": "number"},
                "baseline_rhr_bpm": {"type": "number"},
                "respiratory_rate": {"type": "number", "description": "Day's respiratory rate (breaths/min)"},
                "baseline_respiratory_rate": {"type": "number"},
                "sleep_performance_pct": {"type": "number"},
                "strain": {"type": "number", "description": "Day strain on WHOOP's 0-21 scale"},
                "actual_sleep_h": {"type": "number"},
                "recent_nights_h": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": "Recent nights' asleep hours (most-recent-last) for accumulated debt",
                },
                "sleep_need_h": {"type": "number", "default": DEFAULT_SLEEP_NEED_H},
                "sleep_debt_window_nights": {"type": "integer", "default": DEFAULT_SLEEP_DEBT_WINDOW_NIGHTS},
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
            respiratory_rate=payload.get("respiratory_rate"),
            baseline_respiratory_rate=payload.get("baseline_respiratory_rate"),
            baseline_hrv_ln_sd=payload.get("baseline_hrv_ln_sd"),
        )

        metrics: List[Dict[str, Any]] = [{
            "id": "obs-recovery-score-%s" % (day or "session"),
            "record_type": "Observation",
            "source_id": "recovery",
            "title": "Recovery score",
            "summary": "Recovery %.0f/100 (HRV-led blend, ln-rMSSD) on %s." % (rec["score"], day or "session"),
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

        notes: List[str] = ["recovery_score uses %s (method: %s)" % (rec["algo_version"], rec["method"])]
        if rec["missing"]:
            notes.append("partial inputs; missing components: %s" % ", ".join(rec["missing"]))
        if rec["hrv_ln_sd_is_default"]:
            notes.append("HRV ln-SD baseline too short; used default spread %.2f" % rec["hrv_ln_sd_used"])

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
            sd = sleep_debt(
                actual_sleep_h,
                payload.get("sleep_need_h", DEFAULT_SLEEP_NEED_H),
                recent_nights_h=payload.get("recent_nights_h"),
                window_nights=payload.get("sleep_debt_window_nights", DEFAULT_SLEEP_DEBT_WINDOW_NIGHTS),
            )
            acc = sd.get("accumulated_debt_h")
            summary = "Sleep debt %.1f h (slept %.1f of %.1f h need) on %s." % (
                sd["sleep_debt_h"], sd["actual_sleep_h"], sd["need_h"], day or "session"
            )
            if acc is not None:
                summary += " Accumulated %.1f h over %d nights." % (acc, sd["debt_window_nights"])
            metrics.append({
                "id": "obs-recovery-sleepdebt-%s" % (day or "session"),
                "record_type": "Observation",
                "source_id": "recovery",
                "title": "Sleep debt",
                "summary": summary,
                "artifact_ids": [],
                "evidence_class": "derived-metric",
                "confidence": 0.3,  # need is an estimate, not a measurement (C2)
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
