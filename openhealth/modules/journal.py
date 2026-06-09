"""Journal module — low-friction daily behavior check-ins (WHOOP-style).

A person picks a small set of behaviors to track (``setup``) and then logs them
each day (``compute`` = a daily check-in). The behavior catalog itself lives in
``openhealth.journal_behaviors`` (a static JSON resource transcribed from the
WHOOP Journal screens). This module turns a day's answers into canonical
``Observation`` records plus one ``ContextNote`` summary so they flow into the
same SQLite index, contexts and correlation analysis as everything else.

Design goal is minimal friction: the whole point is that a check-in takes
seconds. Answers are simple — yes/no for most behaviors, a number for the few
``quantity`` ones, a clock time for ``time`` ones. "About yesterday" is just a
check-in with an explicit earlier ``date``.

Nothing here diagnoses. This is observational self-tracking, not medical advice.
Pure stdlib, zero external deps (core rule).
"""

from datetime import date as _date
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .. import journal_behaviors as catalog
from .base import ModuleResult, register

MIN_SELECTION = 3
MAX_SELECTION = 5

SOURCE_ID = "journal"


# --- small helpers ---------------------------------------------------------

def today_iso() -> str:
    """Today's date (UTC) as ISO ``YYYY-MM-DD``."""
    return datetime.now(timezone.utc).date().isoformat()


def yesterday_iso() -> str:
    """Yesterday's date (UTC) — used by the "about yesterday" quick entry."""
    return (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()


def _valid_date(value: str) -> str:
    # Raises ValueError on a malformed date; we keep dates honest (core rule:
    # do not invent dates).
    _date.fromisoformat(value)
    return value


def _coerce_value(behavior: Dict[str, Any], raw: Any) -> Any:
    """Coerce a raw answer to the behavior's declared answer_type.

    - boolean: truthy/falsey, yes/no/y/n/1/0 strings -> bool
    - quantity: -> float
    - time: -> "HH:MM" string (validated)
    """
    atype = behavior["answer_type"]
    if atype == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, (int, float)):
            return bool(raw)
        if isinstance(raw, str):
            s = raw.strip().lower()
            if s in ("yes", "y", "true", "t", "1"):
                return True
            if s in ("no", "n", "false", "f", "0", ""):
                return False
        raise ValueError("behavior %r expects yes/no, got %r" % (behavior["id"], raw))
    if atype == "quantity":
        return float(raw)
    if atype == "time":
        s = str(raw).strip()
        # Validate HH:MM
        datetime.strptime(s, "%H:%M")
        return s
    raise ValueError("unknown answer_type %r" % atype)


# --- setup -----------------------------------------------------------------

def setup(behavior_ids: List[str]) -> Dict[str, Any]:
    """Validate a 3-5 behavior selection and return a ``ContextNote`` dict.

    Raises ValueError if the count is out of range or an id is unknown. The
    returned record stores the selection in ``metadata.selected`` so a later
    check-in (and the UI) can read which behaviors are active.
    """
    if not (MIN_SELECTION <= len(behavior_ids) <= MAX_SELECTION):
        raise ValueError(
            "pick between %d and %d behaviors to keep friction low (got %d)"
            % (MIN_SELECTION, MAX_SELECTION, len(behavior_ids))
        )
    resolved: List[Dict[str, Any]] = []
    for bid in behavior_ids:
        b = catalog.resolve(bid)
        if b is None:
            raise ValueError("unknown behavior %r (see journal_behaviors catalog)" % bid)
        resolved.append(b)

    selected = [
        {"id": b["id"], "name": b["name"], "category": b["category"], "answer_type": b["answer_type"]}
        for b in resolved
    ]
    names = ", ".join(b["name"] for b in resolved)
    return {
        "id": "journal-setup",
        "record_type": "ContextNote",
        "source_id": SOURCE_ID,
        "title": "Journal behaviors selected",
        "summary": "Tracking %d behaviors daily: %s." % (len(resolved), names),
        "artifact_ids": [],
        "evidence_class": "personal",
        "confidence": 1.0,
        "date": today_iso(),
        "tags": ["journal", "setup"],
        "metadata": {"selected": selected},
        "note_kind": "journal_setup",
        "themes": sorted({b["category"] for b in resolved}),
    }


def active_behavior_ids(setup_record: Optional[Dict[str, Any]]) -> List[str]:
    """Read the active behavior ids out of a stored setup record (or [])."""
    if not setup_record:
        return []
    return [s["id"] for s in setup_record.get("metadata", {}).get("selected", [])]


# --- check-in (the module's compute) ---------------------------------------

class JournalModule:
    id = "journal"
    name = "Journal — daily behavior check-in"
    domain = "journal"
    summary = "Logs a day's behavior answers (yes/no, quantity, time) into Observations + a day note."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "JournalCheckinInput",
            "type": "object",
            "required": ["entries"],
            "properties": {
                "date": {
                    "type": "string",
                    "description": "ISO date being logged. Defaults to today; pass yesterday for 'about yesterday'.",
                },
                "entries": {
                    "type": "object",
                    "description": "Map of behavior id (or English name) -> answer (bool / number / HH:MM).",
                    "additionalProperties": True,
                },
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        entries = payload.get("entries") or {}
        if not entries:
            raise ValueError("need at least one behavior entry for a check-in")
        day = _valid_date(payload.get("date") or today_iso())

        metrics: List[Dict[str, Any]] = []
        logged: List[Dict[str, Any]] = []
        for key, raw in entries.items():
            behavior = catalog.resolve(key)
            if behavior is None:
                raise ValueError("unknown behavior %r (see journal_behaviors catalog)" % key)
            value = _coerce_value(behavior, raw)
            bid = behavior["id"]
            metrics.append({
                "id": "obs-journal-%s-%s" % (day, bid),
                "record_type": "Observation",
                "source_id": SOURCE_ID,
                "title": "Journal: %s" % behavior["name"],
                "summary": "%s = %s on %s." % (behavior["name"], value, day),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.9,
                "date": day,
                "tags": ["journal", behavior["category"], bid],
                "metadata": {
                    "behavior_id": bid,
                    "behavior_name": behavior["name"],
                    "category": behavior["category"],
                    "answer_type": behavior["answer_type"],
                },
                "observation_kind": "journal_entry",
                "metric_name": bid,
                "value": value,
                "unit": None,
            })
            logged.append({"id": bid, "name": behavior["name"], "value": value})

        yes = [e["name"] for e in logged if e["value"] is True]
        summary_bits = []
        if yes:
            summary_bits.append("yes: %s" % ", ".join(yes))
        nonbool = [e for e in logged if not isinstance(e["value"], bool)]
        if nonbool:
            summary_bits.append("; ".join("%s=%s" % (e["name"], e["value"]) for e in nonbool))
        day_note = {
            "id": "journal-checkin-%s" % day,
            "record_type": "ContextNote",
            "source_id": SOURCE_ID,
            "title": "Journal check-in %s" % day,
            "summary": "Logged %d behavior(s) for %s. %s" % (len(logged), day, " | ".join(summary_bits)),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.95,
            "date": day,
            "tags": ["journal", "checkin"],
            "metadata": {"date": day, "entries": logged},
            "note_kind": "journal_checkin",
            "themes": sorted({catalog.resolve(e["id"])["category"] for e in logged}),
        }

        notes = ["journal check-in for %s: %d entries" % (day, len(logged))]
        return ModuleResult(metrics=metrics, insights=[day_note], notes=notes)


def persist(result: ModuleResult, db_path) -> int:
    """Write a check-in's metrics + day note into the SQLite index.

    Returns the number of records written. Kept here (not in compute) so the
    module's compute() stays a pure function like the other domains.
    """
    from .. import index

    written = 0
    for rec in list(result.metrics) + list(result.insights):
        index.upsert_record(db_path, rec)
        written += 1
    return written


def persist_setup(setup_record: Dict[str, Any], db_path) -> None:
    """Write the setup record (active selection) into the index."""
    from .. import index

    index.upsert_record(db_path, setup_record)


register(JournalModule())
