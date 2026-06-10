"""VO2max module — a cautious, estimate-only cardiorespiratory-fitness read.

There is no lab cart here, so this never *measures* VO2max — it *estimates* it
from heart-rate ratios using the Heart Rate Ratio Method of Uth, Sørensen,
Overgaard & Pedersen (2004):

    VO2max ≈ 15.3 × (HRmax / HRrest)   [ml/(kg·min)]

Inputs come from data OpenHealth already ingests: ``HRmax`` from a WHOOP body
measurement when present (a measured max, not an age formula), and ``HRrest``
from the current resting heart rate. When no measured HRmax exists we may fall
back to the age estimate ``220 − age`` if an age is known; otherwise we refuse
honestly rather than invent a number.

Why this is always C2 (weak signal), with an explicit disclaimer:
- The Uth formula was validated on *well-trained men aged 21-51*; transfer to
  women, untrained, or older people is uncertain.
- It is most reliable with a *measured* HRmax; ``220 − age`` carries large
  individual error.
- This is an estimate, not a laboratory VO2max, and never a fitness verdict —
  only a range to review.

An optional fitness-category interpretation (by sex/age, ACSM-style bands) is
attached *only* when sex and age are supplied; with bare inputs we return just
the number at C2. Pure stdlib, zero external deps (core rule).
"""

from typing import Any, Dict, List, Optional, Tuple

from .. import evidence
from .base import ModuleResult, register

# --- algorithm version (bump on any formula change) ------------------------
ALGO_VERSIONS: Dict[str, str] = {
    "vo2max": "vo2max@v1",
}

# Uth-Sørensen-Overgaard-Pedersen (2004) coefficient.
UTH_COEFFICIENT = 15.3

# Plausibility guard for the estimate (ml/kg/min). Outside this we flag it.
_VO2_MIN = 10.0
_VO2_MAX = 90.0

DISCLAIMER = (
    "Estimate only (Uth 2004 heart-rate-ratio method), not a measured VO2max. "
    "Validated on well-trained men 21-51; most reliable with a measured HRmax. "
    "Treat as a rough range to review, not a fitness verdict."
)

# ACSM-style VO2max category bands (ml/kg/min) by sex and age decade. Rough,
# population reference only — attached as an optional interpretation, never a
# diagnosis. Keys: sex -> list of (age_lo, age_hi_inclusive, [(label, floor)...]).
# A value at or above a floor earns that label (checked best-first).
_CATEGORY_BANDS: Dict[str, List[Tuple[int, int, List[Tuple[str, float]]]]] = {
    "male": [
        (18, 29, [("excellent", 52.0), ("good", 46.0), ("fair", 42.0), ("poor", 0.0)]),
        (30, 39, [("excellent", 50.0), ("good", 44.0), ("fair", 40.0), ("poor", 0.0)]),
        (40, 49, [("excellent", 47.0), ("good", 41.0), ("fair", 37.0), ("poor", 0.0)]),
        (50, 59, [("excellent", 43.0), ("good", 37.0), ("fair", 34.0), ("poor", 0.0)]),
        (60, 120, [("excellent", 39.0), ("good", 33.0), ("fair", 30.0), ("poor", 0.0)]),
    ],
    "female": [
        (18, 29, [("excellent", 44.0), ("good", 39.0), ("fair", 35.0), ("poor", 0.0)]),
        (30, 39, [("excellent", 42.0), ("good", 37.0), ("fair", 33.0), ("poor", 0.0)]),
        (40, 49, [("excellent", 39.0), ("good", 34.0), ("fair", 31.0), ("poor", 0.0)]),
        (50, 59, [("excellent", 35.0), ("good", 31.0), ("fair", 28.0), ("poor", 0.0)]),
        (60, 120, [("excellent", 32.0), ("good", 28.0), ("fair", 25.0), ("poor", 0.0)]),
    ],
}


def _category(vo2: float, sex: Optional[str], age: Optional[float]) -> Optional[str]:
    """ACSM-style fitness category, only when sex+age are both known."""
    if sex is None or age is None:
        return None
    key = str(sex).strip().lower()
    if key in ("m", "man", "male"):
        key = "male"
    elif key in ("f", "w", "woman", "female"):
        key = "female"
    if key not in _CATEGORY_BANDS:
        return None
    for lo, hi, bands in _CATEGORY_BANDS[key]:
        if lo <= age <= hi:
            for label, floor in bands:
                if vo2 >= floor:
                    return label
    return None


def estimate_vo2max(
    hr_max: Optional[float],
    hr_rest: Optional[float],
    age: Optional[float] = None,
    sex: Optional[str] = None,
) -> Dict[str, Any]:
    """Estimate VO2max (ml/kg/min) via the Uth heart-rate-ratio method.

    HRmax source priority: measured ``hr_max`` (preferred) > age estimate
    ``220 - age`` (only if age is known). If neither is available *and* HRrest
    is missing, raises ValueError — we refuse rather than fabricate.

    Always returns ``confidence: "C2"`` with a disclaimer. Adds a fitness
    ``category`` only when both sex and age are supplied.
    """
    if hr_rest is None or float(hr_rest) <= 0:
        raise ValueError("a positive resting heart rate (HRrest) is required")
    hr_rest = float(hr_rest)

    hrmax_source: str
    if hr_max is not None and float(hr_max) > 0:
        hr_max_used = float(hr_max)
        hrmax_source = "measured"
    elif age is not None and float(age) > 0:
        hr_max_used = 220.0 - float(age)
        hrmax_source = "age_estimate_220_minus_age"
    else:
        raise ValueError(
            "no HRmax available: provide a measured HRmax or an age for the "
            "220 - age fallback (refusing to estimate without one)"
        )

    vo2 = UTH_COEFFICIENT * (hr_max_used / hr_rest)
    plausible = _VO2_MIN <= vo2 <= _VO2_MAX

    out: Dict[str, Any] = {
        "vo2max": round(vo2, 1),
        "unit": "ml/kg/min",
        "method": "uth_2004_hr_ratio",
        "formula": "15.3 * HRmax / HRrest",
        "hr_max_used": round(hr_max_used, 1),
        "hr_rest_used": round(hr_rest, 1),
        "hrmax_source": hrmax_source,
        "plausible_range": plausible,
        "confidence": evidence.Confidence.C2.value,
        "disclaimer": DISCLAIMER,
        "algo_version": ALGO_VERSIONS["vo2max"],
    }

    cat = _category(vo2, sex, age)
    if cat is not None:
        out["category"] = cat
        out["category_note"] = "ACSM-style population band by sex/age; rough reference only"
    return out


# --- index reader ----------------------------------------------------------

def _latest_metric_value(records: List[Dict[str, Any]], obs_kind: str, metric_name: str, day: str) -> Optional[float]:
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


def from_index(
    db_path,
    day: str,
    age: Optional[float] = None,
    sex: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble a vo2max payload for ``day`` from indexed WHOOP records.

    HRmax: WHOOP body measurement (measured) when present. HRrest: most recent
    resting heart rate on/before ``day``. ``age``/``sex`` are optional and only
    drive the category interpretation. Reads only through the index API.
    """
    from .. import index

    records = index.list_records(db_path, "Observation")
    hr_max = _latest_metric_value(records, "whoop_body_measurement", "max_heart_rate", day)
    hr_rest = _latest_metric_value(records, "whoop_recovery_metric", "resting_heart_rate", day)

    return {
        "date": day,
        "hr_max": hr_max,
        "hr_rest": hr_rest,
        "age": age,
        "sex": sex,
    }


# --- module ----------------------------------------------------------------

class VO2MaxModule:
    id = "vo2max"
    name = "VO2max — estimated cardiorespiratory fitness (Uth HR-ratio)"
    domain = "pulse"
    summary = "Estimates VO2max from HRmax/HRrest (Uth 2004); always C2, estimate not measurement."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "VO2MaxInput",
            "type": "object",
            "required": ["hr_rest"],
            "properties": {
                "date": {"type": "string"},
                "hr_max": {"type": "number", "description": "Measured maximum heart rate (bpm); preferred"},
                "hr_rest": {"type": "number", "description": "Resting heart rate (bpm)"},
                "age": {"type": "number", "description": "Optional; enables 220-age fallback and category"},
                "sex": {"type": "string", "description": "Optional 'male'/'female' for category interpretation"},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        day = payload.get("date")
        est = estimate_vo2max(
            hr_max=payload.get("hr_max"),
            hr_rest=payload.get("hr_rest"),
            age=payload.get("age"),
            sex=payload.get("sex"),
        )

        cat = est.get("category")
        summary_txt = "Estimated VO2max ~%.1f %s (%s)." % (
            est["vo2max"], est["unit"], est["hrmax_source"].replace("_", " ")
        )
        if cat:
            summary_txt += " Category: %s." % cat

        metric = {
            "id": "obs-vo2max-%s" % (day or "session"),
            "record_type": "Observation",
            "source_id": "vo2max",
            "title": "VO2max (estimated)",
            "summary": summary_txt + " " + DISCLAIMER,
            "artifact_ids": [],
            "evidence_class": "derived-metric",
            "confidence": evidence.confidence_to_numeric(evidence.Confidence.C2),
            "date": day,
            "tags": ["pulse", "vo2max", "fitness", "estimate", "review-needed"],
            "metadata": est,
            "observation_kind": "vo2max",
            "metric_name": "vo2max",
            "value": est["vo2max"],
            "unit": "ml/kg/min",
        }

        notes = ["vo2max uses %s; %s" % (est["algo_version"], DISCLAIMER)]
        if not est["plausible_range"]:
            notes.append("estimate is outside the plausible 10-90 ml/kg/min range; check inputs")
        return ModuleResult(metrics=[metric], insights=[], notes=notes)


register(VO2MaxModule())
