"""Travel & Timezone module — location periods as health context.

Flights and timezone shifts disrupt recovery and sleep: circadian phase needs
roughly one day per crossed hour to re-entrain, and eastward travel (phase
advance) is harder than westward (phase delay). This module turns a list of
``location periods`` (where you were, in which UTC offset, between which dates)
into:

- ``TimelineEvent`` records, one per stay, anchoring the chronology.
- timezone-shift detections between consecutive stays (a proxy for a flight),
  labelled with direction and the number of crossed hours.
- ``ContextNote`` records covering the jetlag-adaptation window after each
  shift, so the recovery / sleep / correlations modules can treat those days as
  a known confounder rather than a mysterious dip.

This is *context*, not a verdict. Adaptation length is a rule-of-thumb estimate
(personal pattern), capped at a weak/hypothesis confidence and phrased as a
prompt to review, never as a diagnosis. Pure stdlib, zero external deps.
"""

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .base import ModuleResult, register
from .. import evidence


# Crossing this many timezone hours (in either direction) counts as a shift
# worth flagging. One hour is within normal day-to-day drift and noise.
MIN_SHIFT_HOURS = 1

# Rule-of-thumb re-entrainment rate. Circadian phase shifts at roughly this many
# hours per day, faster going west (phase delay) than east (phase advance).
# These are deliberately conservative, round numbers — not a measurement.
ADAPT_HOURS_PER_DAY_WEST = 1.5  # westward / phase delay re-entrains faster
ADAPT_HOURS_PER_DAY_EAST = 1.0  # eastward / phase advance is the hard direction

# Never claim more than this many adaptation days for a single shift, however
# large the offset — past a point it is sleep-debt territory we do not model.
MAX_ADAPT_DAYS = 12


def _parse_date(value: str) -> date:
    """Parse an ISO date (or the date part of an ISO datetime)."""

    return datetime.fromisoformat(value.replace("Z", "+00:00")).date()


def _direction(delta_hours: int) -> str:
    """Travel direction implied by an offset change.

    A larger (more positive) UTC offset lies to the east, so moving to it is an
    eastward trip and a circadian *phase advance* — the harder adaptation.
    """

    if delta_hours > 0:
        return "east"
    if delta_hours < 0:
        return "west"
    return "none"


def adaptation_days(delta_hours: int) -> int:
    """Estimated days to re-entrain after a shift of ``delta_hours`` timezones.

    Eastward (phase advance) is modelled as slower than westward. The result is
    a ceiling-rounded, capped, rule-of-thumb estimate — explicitly not measured.
    """

    crossed = abs(delta_hours)
    if crossed < MIN_SHIFT_HOURS:
        return 0
    rate = ADAPT_HOURS_PER_DAY_EAST if delta_hours > 0 else ADAPT_HOURS_PER_DAY_WEST
    raw = crossed / rate
    days = int(raw) + (1 if raw > int(raw) else 0)  # ceil without float surprises
    return min(days, MAX_ADAPT_DAYS)


def normalize_periods(periods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate and sort location periods by start date.

    Each period needs ``start`` and ``tz_offset_hours``; ``city`` and ``end``
    are optional. ``end`` may be omitted for an ongoing stay. Returns shallow
    copies with parsed ``_start`` / ``_end`` ``date`` objects attached for
    internal use, leaving the caller's input untouched.
    """

    out: List[Dict[str, Any]] = []
    for i, p in enumerate(periods):
        if "start" not in p:
            raise ValueError("period %d is missing 'start'" % i)
        if "tz_offset_hours" not in p:
            raise ValueError("period %d is missing 'tz_offset_hours'" % i)
        start = _parse_date(p["start"])
        end = _parse_date(p["end"]) if p.get("end") else None
        if end is not None and end < start:
            raise ValueError("period %d end is before start" % i)
        item = dict(p)
        item["_start"] = start
        item["_end"] = end
        out.append(item)
    out.sort(key=lambda x: x["_start"])
    return out


def detect_shifts(periods: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Find timezone shifts between consecutive stays (flight proxies).

    Returns one record per crossing whose absolute offset change is at least
    ``MIN_SHIFT_HOURS``, in chronological order. Each record carries the from/to
    cities and offsets, the signed and absolute hour delta, the direction, the
    shift date (the later stay's start), and the estimated adaptation window.
    """

    norm = normalize_periods(periods)
    shifts: List[Dict[str, Any]] = []
    for prev, cur in zip(norm, norm[1:]):
        delta = int(cur["tz_offset_hours"]) - int(prev["tz_offset_hours"])
        if abs(delta) < MIN_SHIFT_HOURS:
            continue
        adapt = adaptation_days(delta)
        shift_day = cur["_start"]
        shifts.append({
            "date": shift_day.isoformat(),
            "from_city": prev.get("city"),
            "to_city": cur.get("city"),
            "from_offset_hours": int(prev["tz_offset_hours"]),
            "to_offset_hours": int(cur["tz_offset_hours"]),
            "delta_hours": delta,
            "crossed_hours": abs(delta),
            "direction": _direction(delta),
            "adaptation_days": adapt,
            "adaptation_end": (shift_day + timedelta(days=max(adapt - 1, 0))).isoformat(),
        })
    return shifts


def jetlag_days(shift: Dict[str, Any]) -> List[str]:
    """ISO dates inside a shift's adaptation window, starting on the shift date."""

    start = _parse_date(shift["date"])
    return [(start + timedelta(days=d)).isoformat() for d in range(shift["adaptation_days"])]


def is_jetlag_day(periods: List[Dict[str, Any]], day: str) -> bool:
    """Whether ``day`` falls inside any detected adaptation window.

    Convenience predicate for other modules: given the same location periods,
    answer whether a given date is a likely-jetlagged day (a confounder).
    """

    target = _parse_date(day)
    for shift in detect_shifts(periods):
        start = _parse_date(shift["date"])
        end = start + timedelta(days=max(shift["adaptation_days"] - 1, 0))
        if shift["adaptation_days"] > 0 and start <= target <= end:
            return True
    return False


def location_on(periods: List[Dict[str, Any]], day: str) -> Optional[Dict[str, Any]]:
    """The stay covering ``day`` (city + offset), or None if uncovered.

    A period with no ``end`` is treated as open-ended (ongoing).
    """

    target = _parse_date(day)
    norm = normalize_periods(periods)
    match: Optional[Dict[str, Any]] = None
    for p in norm:
        if p["_start"] <= target and (p["_end"] is None or target <= p["_end"]):
            match = p
    if match is None:
        return None
    return {"city": match.get("city"), "tz_offset_hours": int(match["tz_offset_hours"])}


def _label(city: Optional[str], offset: int) -> str:
    sign = "+" if offset >= 0 else "-"
    return "%s (UTC%s%d)" % (city or "unknown", sign, abs(offset))


class TravelModule:
    """HealthModule turning location periods into timeline + jetlag context."""

    id = "travel"
    name = "Travel & Timezone — location periods and jetlag context"
    # No dedicated travel/context domain exists yet in base.KNOWN_DOMAINS; this
    # is day-level life context, so it rides the closest existing domain.
    # If a "context" or "travel" domain is added later, switch this constant.
    domain = "journal"
    summary = (
        "Location periods, timezone-shift (flight) detection, and jetlag windows "
        "marked as recovery/sleep context — not a verdict."
    )

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "TravelInput",
            "type": "object",
            "required": ["periods"],
            "properties": {
                "periods": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["start", "tz_offset_hours"],
                        "properties": {
                            "start": {"type": "string", "description": "ISO date stay began"},
                            "end": {"type": "string", "description": "ISO date stay ended (omit if ongoing)"},
                            "city": {"type": "string"},
                            "tz_offset_hours": {
                                "type": "integer",
                                "description": "UTC offset in hours for this location",
                            },
                        },
                    },
                }
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        periods = payload.get("periods", [])
        if not periods:
            raise ValueError("need at least one location period")

        norm = normalize_periods(periods)
        metrics: List[Dict[str, Any]] = []

        # One TimelineEvent per stay — the chronological backbone.
        for i, p in enumerate(norm):
            start_iso = p["_start"].isoformat()
            end_iso = p["_end"].isoformat() if p["_end"] is not None else None
            metrics.append({
                "id": "travel-stay-%s-%d" % (start_iso, i),
                "record_type": "TimelineEvent",
                "source_id": "travel",
                "title": "Stay: %s" % (p.get("city") or "unknown location"),
                "summary": "At %s from %s%s." % (
                    _label(p.get("city"), int(p["tz_offset_hours"])),
                    start_iso,
                    " to %s" % end_iso if end_iso else " (ongoing)",
                ),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.95,
                "date": start_iso,
                "start_date": start_iso,
                "end_date": end_iso,
                "location": p.get("city"),
                "tags": ["travel", "location"],
                "metadata": {"tz_offset_hours": int(p["tz_offset_hours"])},
                "event_kind": "location_period",
                "related_record_ids": [],
            })

        shifts = detect_shifts(periods)
        insights: List[Dict[str, Any]] = []

        # Each shift becomes a flight TimelineEvent plus a jetlag ContextNote.
        for s in shifts:
            shift_id = "travel-shift-%s" % s["date"]
            metrics.append({
                "id": shift_id,
                "record_type": "TimelineEvent",
                "source_id": "travel",
                "title": "Timezone shift (%s, %dh)" % (s["direction"], s["crossed_hours"]),
                "summary": "Moved %s from %s to %s, crossing %d timezone hour(s)." % (
                    s["direction"],
                    _label(s["from_city"], s["from_offset_hours"]),
                    _label(s["to_city"], s["to_offset_hours"]),
                    s["crossed_hours"],
                ),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.9,
                "date": s["date"],
                "location": s["to_city"],
                "tags": ["travel", "timezone-shift", "flight"],
                "metadata": s,
                "event_kind": "timezone_shift",
                "related_record_ids": [],
            })

            days = jetlag_days(s)
            if not days:
                continue

            # Jetlag window: a personal rule-of-thumb -> capped weak/hypothesis,
            # framed as a question, tagged so other modules treat it as context.
            conf = evidence.cap_personal_pattern(evidence.Confidence.C3, validated_switches=0)
            harder = " Eastward shifts (phase advance) usually take longer to adjust." if s["direction"] == "east" else ""
            text = (
                "After the %dh %s shift on %s, the next ~%d day(s) may show reduced "
                "recovery and disrupted sleep while your body clock re-entrains.%s"
                % (s["crossed_hours"], s["direction"], s["date"], s["adaptation_days"], harder)
            )
            note_id = "travel-jetlag-%s" % s["date"]
            insights.append({
                "id": note_id,
                "record_type": "ContextNote",
                "source_id": "travel",
                "title": "Jetlag adaptation window",
                "summary": evidence.frame_statement(text, conf),
                "artifact_ids": [],
                "evidence_class": "derived-hypothesis",
                "confidence": evidence.confidence_to_numeric(conf),
                "date": s["date"],
                "start_date": days[0],
                "end_date": days[-1],
                "location": s["to_city"],
                "tags": ["travel", "jetlag", "context", "review-needed"],
                "metadata": {
                    "shift_id": shift_id,
                    "jetlag_days": days,
                    "direction": s["direction"],
                    "crossed_hours": s["crossed_hours"],
                    "limits": "rule-of-thumb adaptation rate; no measured circadian phase",
                },
                "note_kind": "jetlag",
                "themes": ["travel", "circadian", "recovery"],
            })

        notes = [
            "%d stay(s), %d timezone shift(s) detected" % (len(norm), len(shifts)),
        ]
        if shifts:
            notes.append(
                "jetlag context spans %d day(s) total"
                % sum(sh["adaptation_days"] for sh in shifts)
            )
        return ModuleResult(metrics=metrics, insights=insights, notes=notes)


# NOTE: intentionally NOT calling register(TravelModule()) here.
# The "travel" id maps to domain "journal" (no dedicated travel/context domain
# exists in base.KNOWN_DOMAINS yet). Registration is wired up by the maintainer
# in modules/__init__.py. To register:
#
#     from .travel import TravelModule
#     register(TravelModule())
#
# `TravelModule` and the pure helpers (detect_shifts, adaptation_days,
# is_jetlag_day, location_on, jetlag_days, normalize_periods) are the exports.
__all__ = [
    "TravelModule",
    "normalize_periods",
    "detect_shifts",
    "adaptation_days",
    "jetlag_days",
    "is_jetlag_day",
    "location_on",
]
