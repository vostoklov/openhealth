"""Reference ranges and unit handling for lab markers.

CRITICAL DESIGN RULE: there is no single "correct" reference range. Ranges
depend on the lab, assay, age, sex and more. So the system always prefers the
reference range printed on the user's own lab report. The table below is only a
FALLBACK for orientation, and any flag computed from it is marked
`reference_source="fallback"` so it is never mistaken for the lab's own call.

Marker identity is keyed by a stable internal slug and carries its LOINC code
(test identity) and a UCUM-style unit. Conversion factors convert the
conventional unit to the SI unit (multiply) where both are commonly reported.

Sources for fallback ranges (orientation only, adult): NIH MedlinePlus, ADA
(HbA1c), NGSP (HbA1c conversion), common ARUP/Mayo public tables. Always defer
to the lab report.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple


@dataclass
class MarkerSpec:
    key: str
    display_name: str
    loinc: Optional[str]
    unit: str                      # conventional unit (UCUM-ish)
    si_unit: Optional[str] = None
    to_si_factor: Optional[float] = None  # conventional * factor = SI
    # Fallback range as (low, high) in the conventional unit. Either bound may
    # be None for one-sided markers (e.g. vitamin D has only a lower target).
    fallback_low: Optional[float] = None
    fallback_high: Optional[float] = None
    # Optional sex-specific fallbacks: {"male": (low, high), "female": (...)}.
    sex_ranges: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)
    aliases: List[str] = field(default_factory=list)
    note: Optional[str] = None


# Keyed by internal slug. Aliases are lowercased substrings used to recognise a
# marker name as printed on a report.
MARKERS: Dict[str, MarkerSpec] = {
    "hemoglobin": MarkerSpec(
        key="hemoglobin", display_name="Hemoglobin", loinc="718-7",
        unit="g/dL", si_unit="g/L", to_si_factor=10.0,
        sex_ranges={"male": (13.5, 17.5), "female": (12.0, 15.5)},
        aliases=["hemoglobin", "hgb", "haemoglobin"],
    ),
    "wbc": MarkerSpec(
        key="wbc", display_name="White blood cells", loinc="6690-2",
        unit="10^9/L", fallback_low=4.5, fallback_high=11.0,
        aliases=["wbc", "white blood cell", "leukocyte"],
    ),
    "platelets": MarkerSpec(
        key="platelets", display_name="Platelets", loinc="777-3",
        unit="10^9/L", fallback_low=150.0, fallback_high=400.0,
        aliases=["platelet", "plt"],
    ),
    "glucose": MarkerSpec(
        key="glucose", display_name="Glucose (fasting)", loinc="1558-6",
        unit="mg/dL", si_unit="mmol/L", to_si_factor=0.0555,
        fallback_low=70.0, fallback_high=99.0,
        aliases=["glucose", "fasting glucose", "blood sugar"],
    ),
    "creatinine": MarkerSpec(
        key="creatinine", display_name="Creatinine", loinc="2160-0",
        unit="mg/dL", si_unit="umol/L", to_si_factor=88.42,
        fallback_low=0.7, fallback_high=1.3,
        aliases=["creatinine"],
    ),
    "sodium": MarkerSpec(
        key="sodium", display_name="Sodium", loinc="2951-2",
        unit="mmol/L", fallback_low=135.0, fallback_high=145.0,
        aliases=["sodium", "na"],
    ),
    "potassium": MarkerSpec(
        key="potassium", display_name="Potassium", loinc="2823-3",
        unit="mmol/L", fallback_low=3.5, fallback_high=5.0,
        aliases=["potassium", "k+"],
    ),
    "total_cholesterol": MarkerSpec(
        key="total_cholesterol", display_name="Total cholesterol", loinc="2093-3",
        unit="mg/dL", si_unit="mmol/L", to_si_factor=0.02586,
        fallback_high=200.0,
        aliases=["total cholesterol", "cholesterol total", "chol"],
    ),
    "ldl": MarkerSpec(
        key="ldl", display_name="LDL cholesterol", loinc="2089-1",
        unit="mg/dL", si_unit="mmol/L", to_si_factor=0.02586,
        fallback_high=100.0,
        aliases=["ldl"],
    ),
    "hdl": MarkerSpec(
        key="hdl", display_name="HDL cholesterol", loinc="2085-9",
        unit="mg/dL", si_unit="mmol/L", to_si_factor=0.02586,
        sex_ranges={"male": (40.0, None), "female": (50.0, None)},
        aliases=["hdl"],
    ),
    "triglycerides": MarkerSpec(
        key="triglycerides", display_name="Triglycerides", loinc="2571-8",
        unit="mg/dL", si_unit="mmol/L", to_si_factor=0.01129,
        fallback_high=150.0,
        aliases=["triglyceride", "trig"],
    ),
    "vitamin_d": MarkerSpec(
        key="vitamin_d", display_name="Vitamin D (25-OH)", loinc="1989-3",
        unit="ng/mL", si_unit="nmol/L", to_si_factor=2.496,
        fallback_low=30.0,
        aliases=["vitamin d", "25-oh", "25 hydroxy", "25-hydroxyvitamin"],
        note="Below 20 ng/mL is deficiency, 20-30 insufficiency, >=30 sufficient.",
    ),
    "b12": MarkerSpec(
        key="b12", display_name="Vitamin B12", loinc="2132-9",
        unit="pg/mL", si_unit="pmol/L", to_si_factor=0.738,
        fallback_low=200.0, fallback_high=900.0,
        aliases=["b12", "cobalamin"],
    ),
    "ferritin": MarkerSpec(
        key="ferritin", display_name="Ferritin", loinc="2276-4",
        unit="ng/mL", si_unit="ug/L", to_si_factor=1.0,
        sex_ranges={"male": (30.0, 400.0), "female": (15.0, 150.0)},
        aliases=["ferritin"],
        note="Acute-phase reactant: rises with inflammation; read alongside CRP.",
    ),
    "tsh": MarkerSpec(
        key="tsh", display_name="TSH", loinc="3016-3",
        unit="mIU/L", fallback_low=0.4, fallback_high=4.0,
        aliases=["tsh", "thyroid stimulating"],
    ),
    "hba1c": MarkerSpec(
        key="hba1c", display_name="HbA1c", loinc="4548-4",
        unit="%", fallback_high=5.7,
        aliases=["hba1c", "a1c", "glycated", "glycohemoglobin"],
        note="<5.7% normal, 5.7-6.4% prediabetes, >=6.5% diabetes (ADA).",
    ),
    "crp": MarkerSpec(
        key="crp", display_name="C-reactive protein", loinc="1988-5",
        unit="mg/L", fallback_high=3.0,
        aliases=["crp", "c-reactive", "c reactive"],
    ),
    # --- additions for panel completeness (glycemia / iron / thyroid /
    # inflammation / vitamins). Fallbacks are orientation-only adult ranges. ---
    "insulin": MarkerSpec(
        key="insulin", display_name="Insulin (fasting)", loinc="20448-7",
        unit="uIU/mL", si_unit="pmol/L", to_si_factor=6.945,
        fallback_low=2.6, fallback_high=24.9,
        aliases=["insulin", "fasting insulin"],
        note="Fasting insulin; pairs with glucose for HOMA-IR.",
    ),
    "iron": MarkerSpec(
        key="iron", display_name="Serum iron", loinc="2498-4",
        unit="ug/dL", si_unit="umol/L", to_si_factor=0.179,
        fallback_low=60.0, fallback_high=170.0,
        aliases=["serum iron", "iron total", "fe "],
    ),
    "transferrin": MarkerSpec(
        key="transferrin", display_name="Transferrin", loinc="3034-6",
        unit="mg/dL", fallback_low=200.0, fallback_high=360.0,
        aliases=["transferrin"],
    ),
    "t3": MarkerSpec(
        key="t3", display_name="Free T3", loinc="3051-0",
        unit="pg/mL", fallback_low=2.3, fallback_high=4.2,
        aliases=["free t3", "ft3", "triiodothyronine"],
    ),
    "t4": MarkerSpec(
        key="t4", display_name="Free T4", loinc="3024-7",
        unit="ng/dL", fallback_low=0.8, fallback_high=1.8,
        aliases=["free t4", "ft4", "thyroxine"],
    ),
    "folate": MarkerSpec(
        key="folate", display_name="Folate", loinc="2284-8",
        unit="ng/mL", si_unit="nmol/L", to_si_factor=2.266,
        fallback_low=3.0, fallback_high=20.0,
        aliases=["folate", "folic acid", "folacin"],
    ),
    "homocysteine": MarkerSpec(
        key="homocysteine", display_name="Homocysteine", loinc="13965-9",
        unit="umol/L", fallback_high=15.0,
        aliases=["homocysteine", "hcy"],
        note="Elevated homocysteine read alongside B12/folate.",
    ),
}


def match_marker(name: str) -> Optional[MarkerSpec]:
    """Resolve a marker name as printed on a report to a MarkerSpec."""

    if not name:
        return None
    lowered = name.strip().lower()
    if lowered in MARKERS:
        return MARKERS[lowered]
    # Exact display-name match wins before any alias substring, so e.g.
    # "LDL cholesterol" is not mis-resolved to total_cholesterol via the "chol"
    # substring alias.
    for spec in MARKERS.values():
        if spec.display_name.lower() == lowered:
            return spec
    # Prefer the most specific alias match (longest alias that is a substring),
    # so "ldl" beats a generic "chol" when both appear in the name.
    best: Optional[MarkerSpec] = None
    best_len = -1
    for spec in MARKERS.values():
        for alias in spec.aliases:
            if alias in lowered and len(alias) > best_len:
                best, best_len = spec, len(alias)
    return best


def resolve_range(
    spec: MarkerSpec,
    sex: Optional[str] = None,
    report_low: Optional[float] = None,
    report_high: Optional[float] = None,
) -> Tuple[Optional[float], Optional[float], str]:
    """Return (low, high, source).

    Prefers the range printed on the report. Falls back to the table (sex-aware)
    only when the report did not provide one. `source` is "report" or "fallback".
    """

    if report_low is not None or report_high is not None:
        return report_low, report_high, "report"
    if sex and sex.lower() in spec.sex_ranges:
        low, high = spec.sex_ranges[sex.lower()]
        return low, high, "fallback"
    # No sex given but the marker is sex-specific: widen to the union so we do
    # not flag a normal value as abnormal just because sex is unknown.
    if spec.sex_ranges:
        lows = [r[0] for r in spec.sex_ranges.values() if r[0] is not None]
        highs = [r[1] for r in spec.sex_ranges.values() if r[1] is not None]
        return (min(lows) if lows else None, max(highs) if highs else None, "fallback")
    return spec.fallback_low, spec.fallback_high, "fallback"


def flag_value(
    value: Optional[float],
    low: Optional[float],
    high: Optional[float],
) -> str:
    """Classify a value relative to its range: low / normal / high / unknown."""

    if value is None or (low is None and high is None):
        return "unknown"
    if low is not None and value < low:
        return "low"
    if high is not None and value > high:
        return "high"
    return "normal"


def to_si(spec: MarkerSpec, value: Optional[float]) -> Optional[float]:
    """Convert a conventional-unit value to SI, if a factor is known."""

    if value is None or spec.to_si_factor is None:
        return None
    return round(value * spec.to_si_factor, 4)


def assess_marker(
    name: str,
    value: Optional[float],
    unit: Optional[str] = None,
    sex: Optional[str] = None,
    report_low: Optional[float] = None,
    report_high: Optional[float] = None,
) -> Optional[Dict[str, object]]:
    """Full assessment of one lab marker.

    Returns a dict suitable for storing in an Observation's metadata, or None if
    the marker name is not recognised (caller should still keep the raw value).
    """

    spec = match_marker(name)
    if spec is None:
        return None
    low, high, source = resolve_range(spec, sex, report_low, report_high)
    flag = flag_value(value, low, high)
    return {
        "marker_key": spec.key,
        "display_name": spec.display_name,
        "loinc": spec.loinc,
        "value": value,
        "unit": unit or spec.unit,
        "value_si": to_si(spec, value),
        "si_unit": spec.si_unit,
        "reference_low": low,
        "reference_high": high,
        "reference_source": source,
        "flag": flag,
        "note": spec.note,
    }
