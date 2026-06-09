"""Optimal (target) ranges for health markers, kept separate from lab reference ranges.

WHY THIS EXISTS, AND WHY IT IS SEPARATE
---------------------------------------
``openhealth.reference_ranges`` answers one question: "is this value inside the
range a lab would print as normal?" That range is a *population statistical*
band (roughly the central 95% of a reference population), and a value inside it
is, by definition, not flagged by the lab.

This module answers a different, narrower question: "is this value where
preventive / functional-medicine sources suggest it is *optimal* for long-term
health?" An optimal target is usually *tighter* than the lab range and often
sits near one edge of it. Example: a vitamin D of 22 ng/mL is inside the lab
fallback (>=30 is the lab's own cut, 20-30 is "insufficient") yet many sources
target 40-60 ng/mL — so it is "normal-ish by the lab, below optimal here".

These two ideas must never be conflated:

- Reference status comes from the lab (or the fallback table) and is the
  authoritative "is this abnormal" signal. It can trigger red flags.
- Optimal status is a *softer*, evidence-graded preference. It is NOT a
  diagnosis, NOT a treatment target a clinician set for this person, and NOT a
  reason to act alone. Every optimal call this module returns carries an
  explicit "optimum is not a diagnosis" disclaimer.

DESIGN RULES BAKED IN
---------------------
- Optimal ranges live in their own table. We never edit ``reference_ranges``;
  we only read it (to get the lab/reference status and the marker identity).
- Every optimal range carries a ``source`` string, a ``source_url`` and a
  ``Confidence`` level (C1-C5, imported from ``openhealth.evidence``). Most
  optimal targets are C3 ("a hypothesis worth testing", from observational data
  / expert opinion), not C5. We surface that uncertainty, never hide it.
- A value in the *critical* range (per ``evidence.check_critical_lab``) short-
  circuits everything: the only message is "see a clinician". We do not offer an
  optimal interpretation of a value that is itself an emergency.
- Pure stdlib, zero external deps (core rule).

Nothing here is medical advice.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from . import reference_ranges
from .evidence import Confidence, RedFlag, check_critical_lab

# Disclaimer attached to every optimal assessment. Single source of truth so the
# wording stays consistent everywhere the result is rendered.
OPTIMUM_DISCLAIMER = (
    "An optimal range is a cautious, evidence-graded preference for long-term "
    "health, not a diagnosis, a personal target a clinician set for you, or a "
    "reason to change anything on your own. Discuss any change with a clinician."
)


# Direction of "better" for a marker, so a value below/above its optimal band can
# be described correctly (low ferritin is suboptimal-low; high LDL is suboptimal-high).
DIRECTION_RANGE = "range"      # an interior band is best; both tails are suboptimal
DIRECTION_HIGHER = "higher"    # higher is better up to a soft ceiling (e.g. HDL)
DIRECTION_LOWER = "lower"      # lower is better down to a soft floor (e.g. LDL, CRP)


@dataclass
class OptimalRange:
    """An evidence-graded optimal target for one marker.

    ``marker_key`` MUST match a slug in ``reference_ranges.MARKERS`` so the same
    value can be assessed against both the lab reference range and this optimal
    band without re-identifying the marker. Bounds are in the marker's
    *conventional* unit (the same unit ``reference_ranges`` compares in).

    Either bound may be ``None`` for one-sided targets:
    - DIRECTION_LOWER markers set only ``high`` (the soft ceiling of "optimal").
    - DIRECTION_HIGHER markers set only ``low`` (the soft floor of "optimal").
    - DIRECTION_RANGE markers set both.
    """

    marker_key: str
    direction: str                 # one of DIRECTION_*
    low: Optional[float]           # optimal-band lower bound (conventional unit)
    high: Optional[float]          # optimal-band upper bound (conventional unit)
    unit: str                      # conventional unit, mirrors reference_ranges
    confidence: Confidence         # how strong the evidence for THIS target is
    source: str                    # short human-readable provenance
    source_url: str                # citable link (orientation only)
    rationale: Optional[str] = None  # one line on why this differs from the lab range
    sex_ranges: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)


# --- Optimal range table ----------------------------------------------------
#
# Keyed by the SAME slug as reference_ranges.MARKERS. These targets are tighter
# than the lab reference band and reflect preventive / functional sources. They
# are deliberately conservative and each is graded by how solid the evidence is.
# Most are C3 (hypothesis-grade): optimal-range claims rarely rest on RCT outcome
# data. LDL/HbA1c (cardiometabolic risk) get C4 — large outcome evidence that
# *lower is better within range* is consistent, though the exact "optimal" cut is
# still a preference, not a personal prescription.

OPTIMAL_RANGES: Dict[str, OptimalRange] = {
    "vitamin_d": OptimalRange(
        marker_key="vitamin_d",
        direction=DIRECTION_RANGE,
        low=40.0, high=60.0, unit="ng/mL",
        confidence=Confidence.C3,
        source="Endocrine Society / functional targets (orientation)",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK56070/",
        rationale="Lab calls >=30 ng/mL sufficient; many sources target 40-60 for repletion.",
    ),
    "ferritin": OptimalRange(
        marker_key="ferritin",
        direction=DIRECTION_RANGE,
        low=50.0, high=150.0, unit="ng/mL",
        confidence=Confidence.C3,
        source="Iron-repletion literature (orientation); read with CRP",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK557376/",
        rationale="Lab low bound is ~15-30; symptom resolution often needs ferritin "
                  ">=50, but it rises with inflammation.",
        # Optimal floors differ a little by typical iron stores; ceilings shared.
        sex_ranges={"male": (50.0, 150.0), "female": (50.0, 122.0)},
    ),
    "hba1c": OptimalRange(
        marker_key="hba1c",
        direction=DIRECTION_LOWER,
        low=None, high=5.4, unit="%",
        confidence=Confidence.C4,
        source="ADA thresholds + cardiometabolic risk gradient",
        source_url="https://diabetesjournals.org/care/article/47/Supplement_1/S20/153954",
        rationale="Lab/normal is <5.7%; risk rises continuously, so an optimal target sits below ~5.4%.",
    ),
    "glucose": OptimalRange(
        marker_key="glucose",
        direction=DIRECTION_RANGE,
        low=72.0, high=85.0, unit="mg/dL",
        confidence=Confidence.C3,
        source="Fasting-glucose risk gradient (orientation)",
        source_url="https://diabetesjournals.org/care/article/47/Supplement_1/S20/153954",
        rationale="Lab normal is 70-99 mg/dL; lower-normal fasting glucose tracks lower long-term risk.",
    ),
    "ldl": OptimalRange(
        marker_key="ldl",
        direction=DIRECTION_LOWER,
        low=None, high=100.0, unit="mg/dL",
        confidence=Confidence.C4,
        source="AHA/ACC lipid guidance (lower is better within range)",
        source_url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
        rationale="Optimal LDL for primary prevention is generally <100 mg/dL; lower for higher cardiovascular risk.",
    ),
    "hdl": OptimalRange(
        marker_key="hdl",
        direction=DIRECTION_HIGHER,
        low=60.0, high=None, unit="mg/dL",
        confidence=Confidence.C3,
        source="NCEP/AHA: HDL >=60 mg/dL is a negative risk factor",
        source_url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
        rationale="Lab low bound is 40 (male) / 50 (female); >=60 is treated as protective.",
        sex_ranges={"male": (60.0, None), "female": (60.0, None)},
    ),
    "triglycerides": OptimalRange(
        marker_key="triglycerides",
        direction=DIRECTION_LOWER,
        low=None, high=100.0, unit="mg/dL",
        confidence=Confidence.C3,
        source="AHA: optimal triglycerides <100 mg/dL",
        source_url="https://www.ahajournals.org/doi/10.1161/CIR.0000000000000625",
        rationale="Lab 'normal' is <150 mg/dL; <100 is described as optimal.",
    ),
    "total_cholesterol": OptimalRange(
        marker_key="total_cholesterol",
        direction=DIRECTION_LOWER,
        low=None, high=180.0, unit="mg/dL",
        confidence=Confidence.C3,
        source="NCEP desirable total cholesterol (orientation)",
        source_url="https://www.nhlbi.nih.gov/files/docs/guidelines/atp3xsum.pdf",
        rationale="Lab cut is <200 mg/dL; an optimal target is nearer <180. Interpret with LDL/HDL, not alone.",
    ),
    "tsh": OptimalRange(
        marker_key="tsh",
        direction=DIRECTION_RANGE,
        low=0.5, high=2.5, unit="mIU/L",
        confidence=Confidence.C3,
        source="Narrower euthyroid target debate (orientation)",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK499850/",
        rationale="Lab range is ~0.4-4.0; some sources prefer a tighter 0.5-2.5 mIU/L. Contested.",
    ),
    "b12": OptimalRange(
        marker_key="b12",
        direction=DIRECTION_HIGHER,
        low=500.0, high=None, unit="pg/mL",
        confidence=Confidence.C3,
        source="Functional B12 sufficiency (orientation); consider MMA if borderline",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK441923/",
        rationale="Lab low bound ~200 pg/mL; deficiency symptoms can occur in the "
                  "200-400 'grey zone', so >=500 is a softer target.",
    ),
    "crp": OptimalRange(
        marker_key="crp",
        direction=DIRECTION_LOWER,
        low=None, high=1.0, unit="mg/L",
        confidence=Confidence.C4,
        source="AHA/CDC hs-CRP cardiovascular risk strata",
        source_url="https://www.ahajournals.org/doi/10.1161/01.CIR.0000052939.59093.45",
        rationale="hs-CRP <1.0 mg/L is the low-risk stratum (1-3 average, >3 higher). Acute illness invalidates it.",
    ),
    "insulin": OptimalRange(
        marker_key="insulin",
        direction=DIRECTION_LOWER,
        low=None, high=8.0, unit="uIU/mL",
        confidence=Confidence.C3,
        source="Fasting-insulin metabolic-health orientation",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK278970/",
        rationale="Lab 'normal' fasting insulin runs to ~25; many sources prefer <8 uIU/mL "
                  "for metabolic health. Interpret with glucose (HOMA-IR).",
    ),
    "homocysteine": OptimalRange(
        marker_key="homocysteine",
        direction=DIRECTION_LOWER,
        low=None, high=10.0, unit="umol/L",
        confidence=Confidence.C3,
        source="Homocysteine cardiovascular-risk orientation",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK554408/",
        rationale="Lab cut is ~15; lower targets (<10) are preferred preventively. "
                  "Read with B12/folate.",
    ),
    "folate": OptimalRange(
        marker_key="folate",
        direction=DIRECTION_HIGHER,
        low=6.0, high=None, unit="ng/mL",
        confidence=Confidence.C3,
        source="Functional folate sufficiency (orientation)",
        source_url="https://www.ncbi.nlm.nih.gov/books/NBK535377/",
        rationale="Lab low bound ~3 ng/mL; a softer sufficiency floor sits near 6 ng/mL.",
    ),
}


# --- Status vocabulary ------------------------------------------------------
#
# Optimal status is intentionally soft language, never a diagnosis.

OPTIMAL = "optimal"               # inside the optimal band
SUBOPTIMAL_LOW = "below_optimal"  # below the band (for range/higher markers)
SUBOPTIMAL_HIGH = "above_optimal" # above the band (for range/lower markers)
UNKNOWN = "unknown"               # no value, or no optimal range defined


def get_optimal_range(marker_key: str) -> Optional[OptimalRange]:
    """Return the OptimalRange for a marker slug, or None if none is defined."""

    return OPTIMAL_RANGES.get(marker_key)


def has_optimal_range(marker_key: str) -> bool:
    """Whether an optimal target exists for this marker slug."""

    return marker_key in OPTIMAL_RANGES


def _resolve_optimal_bounds(
    opt: OptimalRange, sex: Optional[str]
) -> Tuple[Optional[float], Optional[float]]:
    """Pick the optimal (low, high) bounds, honouring a sex-specific override."""

    if sex and sex.lower() in opt.sex_ranges:
        return opt.sex_ranges[sex.lower()]
    return opt.low, opt.high


def classify_optimal(
    opt: OptimalRange,
    value: Optional[float],
    sex: Optional[str] = None,
) -> str:
    """Classify a value against an optimal band.

    Returns one of OPTIMAL / SUBOPTIMAL_LOW / SUBOPTIMAL_HIGH / UNKNOWN.

    The classification respects the marker's ``direction`` so the labels read
    naturally: a DIRECTION_LOWER marker (e.g. LDL) is only ever OPTIMAL or
    SUBOPTIMAL_HIGH; a DIRECTION_HIGHER marker (e.g. HDL) is only ever OPTIMAL or
    SUBOPTIMAL_LOW; a DIRECTION_RANGE marker can fall on either side.
    """

    if value is None:
        return UNKNOWN
    low, high = _resolve_optimal_bounds(opt, sex)
    if low is None and high is None:
        return UNKNOWN
    if low is not None and value < low:
        return SUBOPTIMAL_LOW
    if high is not None and value > high:
        return SUBOPTIMAL_HIGH
    return OPTIMAL


def _optimal_summary(status: str, opt: OptimalRange) -> str:
    """Cautious, non-diagnostic one-liner for an optimal status.

    Always framed softly. Carries the C-level so the reader sees how strong the
    evidence behind the target is. Never states or implies a diagnosis.
    """

    level = opt.confidence
    tag = "[%s]" % level.value
    if status == OPTIMAL:
        return "%s Within the optimal target some sources prefer. Not a diagnosis." % tag
    if status == SUBOPTIMAL_LOW:
        return (
            "%s Below the optimal target some sources prefer; this is not abnormal by "
            "itself and not a diagnosis. Worth discussing, not acting on alone." % tag
        )
    if status == SUBOPTIMAL_HIGH:
        return (
            "%s Above the optimal target some sources prefer; this is not abnormal by "
            "itself and not a diagnosis. Worth discussing, not acting on alone." % tag
        )
    return "%s No optimal comparison available." % tag


def assess_optima(
    name: str,
    value: Optional[float],
    unit: Optional[str] = None,
    sex: Optional[str] = None,
    report_low: Optional[float] = None,
    report_high: Optional[float] = None,
) -> Optional[Dict[str, object]]:
    """Assess one marker value against BOTH the lab reference range and the optimal band.

    Returns a dict, or ``None`` if the marker name is not recognised at all (the
    caller should keep the raw value and stay cautious — same contract as
    ``reference_ranges.assess_marker``).

    The returned dict always separates the two judgements and never collapses
    them into a single verdict:

    - ``reference_status`` — the authoritative lab/fallback flag
      (low/normal/high/unknown) plus its source (report vs fallback). This is the
      same call ``reference_ranges`` would make.
    - ``optimal_status`` — the soft, evidence-graded preference
      (optimal/below_optimal/above_optimal/unknown) with its confidence level and
      source. ``None`` when no optimal target is defined for the marker.
    - ``red_flag`` — set (and everything else suppressed in meaning) when the
      value is in the critical range; the message routes the user to a clinician.
    - ``disclaimer`` — the standing "optimum is not a diagnosis" note, always present.

    A red flag does not stop us *reporting* the numbers, but the explicit
    contract is: when ``red_flag`` is present the only safe action is to see a
    clinician, and the optimal interpretation must be ignored. We encode that by
    blanking the optimal summary to the red-flag instruction.
    """

    # Reference (lab/fallback) assessment via the upstream module. This also
    # resolves the marker identity; if it can't, neither can we.
    reference = reference_ranges.assess_marker(
        name, value=value, unit=unit, sex=sex,
        report_low=report_low, report_high=report_high,
    )
    if reference is None:
        return None

    marker_key = str(reference["marker_key"])

    # Critical-value short-circuit. A value a lab would call "panic" is an
    # emergency, not an optimization question. We still echo the reference
    # numbers, but the actionable message is "see a clinician".
    red_flag: Optional[RedFlag] = check_critical_lab(marker_key, value)

    opt = get_optimal_range(marker_key)
    optimal_status: Optional[str]
    optimal_low: Optional[float]
    optimal_high: Optional[float]
    optimal_meta: Optional[Dict[str, object]]

    if opt is None:
        optimal_status = None
        optimal_low = None
        optimal_high = None
        optimal_meta = None
    else:
        optimal_low, optimal_high = _resolve_optimal_bounds(opt, sex)
        if red_flag is not None:
            # Do not offer an "optimal" reading of an emergency value.
            optimal_status = UNKNOWN
        else:
            optimal_status = classify_optimal(opt, value, sex=sex)
        optimal_meta = {
            "direction": opt.direction,
            "optimal_low": optimal_low,
            "optimal_high": optimal_high,
            "confidence": opt.confidence.value,
            "source": opt.source,
            "source_url": opt.source_url,
            "rationale": opt.rationale,
        }

    # Human-facing summary line.
    if red_flag is not None:
        summary = red_flag.message
    elif opt is not None and optimal_status is not None:
        summary = _optimal_summary(optimal_status, opt)
    else:
        summary = "No optimal target is defined for this marker; only the lab reference applies."

    return {
        "marker_key": marker_key,
        "display_name": reference["display_name"],
        "value": value,
        "unit": unit or reference["unit"],
        # --- the two separate judgements ---
        "reference_status": reference["flag"],
        "reference_low": reference["reference_low"],
        "reference_high": reference["reference_high"],
        "reference_source": reference["reference_source"],
        "optimal_status": optimal_status,
        "optimal_low": optimal_low,
        "optimal_high": optimal_high,
        "optimal": optimal_meta,
        # --- safety + framing ---
        "red_flag": None if red_flag is None else {
            "code": red_flag.code,
            "message": red_flag.message,
            "urgency": red_flag.urgency,
            "action": "see-clinician",
        },
        "summary": summary,
        "disclaimer": OPTIMUM_DISCLAIMER,
    }


def assess_panel(
    markers: List[Dict[str, object]],
    sex: Optional[str] = None,
) -> List[Dict[str, object]]:
    """Assess a list of ``{name, value, unit}`` marker dicts against both ranges.

    Recognised markers come back with the full dual assessment (see
    ``assess_optima``). Unrecognised markers are passed through with
    ``marker_key=None`` so nothing is silently dropped; the caller keeps the raw
    value. The standing disclaimer is attached to every row.
    """

    out: List[Dict[str, object]] = []
    for m in markers:
        name = str(m.get("name") or m.get("marker") or "")
        raw_value = m.get("value")
        if isinstance(raw_value, bool) or not isinstance(raw_value, (int, float)):
            value = None
        else:
            value = float(raw_value)
        row_sex = str(m["sex"]) if m.get("sex") else sex

        assessment = assess_optima(name, value, unit=m.get("unit"), sex=row_sex)
        if assessment is None:
            out.append({
                "marker_key": None,
                "display_name": name,
                "value": value,
                "unit": m.get("unit"),
                "reference_status": UNKNOWN,
                "optimal_status": None,
                "red_flag": None,
                "summary": "Marker not recognised; kept as a raw value.",
                "disclaimer": OPTIMUM_DISCLAIMER,
                "raw": True,
            })
        else:
            out.append(assessment)
    return out
