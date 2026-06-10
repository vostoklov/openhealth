"""Medications module — the intervention ledger for meds, supplements, habits.

This is the Intervention Agent's home (see AGENTS.md): everything a person
takes or does on purpose — prescription medications, supplements, and habits
(good or bad) — becomes an ``Intervention`` record with a start/end window and
a status. ``compute`` takes the whole ledger and returns:

- one Intervention record per item (the canonical ledger),
- a ledger snapshot note (active items by kind, durations) for the UI/agent,
- a C3 *question* per long-running active med/supplement ("worth discussing a
  review with the prescriber?") — never an instruction to stop or change,
- an honest interaction disclaimer when 2+ meds/supplements are active:
  OpenHealth does NOT check interactions; a doctor or pharmacist does,
- journal-link candidates for habits, so they can be tracked daily and picked
  up by the correlations module ("what affects me").

No diagnosis, no dosing advice. Pure stdlib, zero external deps (core rule).
"""

from datetime import date as _date
from datetime import datetime, timezone
from typing import Any, Dict, List

from .. import evidence
from .. import journal_behaviors as catalog
from ..storage import slugify
from .base import ModuleResult, register

SOURCE_ID = "medications"

KINDS = ("medication", "supplement", "habit_bad", "habit_good")
SCHEDULES = ("morning", "evening", "with_food", "prn", "other")
STATUSES = ("active", "paused", "stopped")
ITEM_SOURCES = ("self", "doctor")

# Active meds/supplements running longer than this many months get a gentle
# "discuss a review with the prescriber" question (C3 — a prompt, not advice).
REVIEW_MONTHS_DEFAULT = 6


# --- helpers -----------------------------------------------------------------


def today_iso() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _valid_date(value: str) -> str:
    # Raises ValueError on a malformed date (core rule: do not invent dates).
    _date.fromisoformat(value)
    return value


def months_between(start_iso: str, end_iso: str) -> float:
    """Approximate months between two ISO dates (30.44-day months)."""
    delta_days = (_date.fromisoformat(end_iso) - _date.fromisoformat(start_iso)).days
    return round(delta_days / 30.44, 1)


def normalize_item(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Validate one ledger item and fill defaults. Raises ValueError loudly."""
    name = str(raw.get("name") or "").strip()
    if not name:
        raise ValueError("ledger item needs a non-empty name")
    kind = raw.get("kind")
    if kind not in KINDS:
        raise ValueError("item %r: kind must be one of %s (got %r)" % (name, ", ".join(KINDS), kind))
    schedule = raw.get("schedule")
    if schedule is not None and schedule not in SCHEDULES:
        raise ValueError("item %r: schedule must be one of %s (got %r)" % (name, ", ".join(SCHEDULES), schedule))
    status = raw.get("status") or "active"
    if status not in STATUSES:
        raise ValueError("item %r: status must be one of %s (got %r)" % (name, ", ".join(STATUSES), status))
    source = raw.get("source") or "self"
    if source not in ITEM_SOURCES:
        raise ValueError("item %r: source must be one of %s (got %r)" % (name, ", ".join(ITEM_SOURCES), source))
    start_date = raw.get("start_date")
    if start_date is not None:
        start_date = _valid_date(start_date)
    end_date = raw.get("end_date")
    if end_date is not None:
        end_date = _valid_date(end_date)
    if status == "stopped" and end_date is None:
        # A stopped item without an end date stays undated rather than invented.
        pass
    return {
        "name": name,
        "kind": kind,
        "dose": raw.get("dose"),
        "schedule": schedule,
        "start_date": start_date,
        "end_date": end_date,
        "status": status,
        "reason": raw.get("reason"),
        "source": source,
        # Optional explicit link to a journal behavior id (for correlations).
        "behavior_id": raw.get("behavior_id"),
    }


def _intervention_kind(kind: str) -> str:
    if kind == "medication":
        return "medication"
    if kind == "supplement":
        return "supplement"
    return "habit"


# --- the module --------------------------------------------------------------


class MedicationsModule:
    id = "medications"
    name = "Medications — meds, supplements & habits ledger"
    domain = "medications"
    summary = "Intervention ledger: meds/supplements/habits with windows, status, review prompts and journal links."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "MedicationsLedgerInput",
            "type": "object",
            "required": ["items"],
            "properties": {
                "items": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["name", "kind"],
                        "properties": {
                            "name": {"type": "string"},
                            "kind": {"type": "string", "enum": list(KINDS)},
                            "dose": {"type": "string"},
                            "schedule": {"type": "string", "enum": list(SCHEDULES)},
                            "start_date": {"type": "string", "description": "ISO date; omit if unknown."},
                            "end_date": {"type": "string"},
                            "status": {"type": "string", "enum": list(STATUSES), "default": "active"},
                            "reason": {"type": "string"},
                            "source": {"type": "string", "enum": list(ITEM_SOURCES), "default": "self"},
                            "behavior_id": {
                                "type": "string",
                                "description": "Optional journal behavior id to link a habit for correlations.",
                            },
                        },
                    },
                },
                "today": {"type": "string", "description": "ISO date override (tests / backfill)."},
                "review_months": {"type": "number", "default": REVIEW_MONTHS_DEFAULT},
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        raw_items = payload.get("items") or []
        if not raw_items:
            raise ValueError("need at least one ledger item")
        today = _valid_date(payload.get("today") or today_iso())
        review_months = float(payload.get("review_months") or REVIEW_MONTHS_DEFAULT)

        items = [normalize_item(raw) for raw in raw_items]
        metrics: List[Dict[str, Any]] = []
        insights: List[Dict[str, Any]] = []
        active_by_kind: Dict[str, List[Dict[str, Any]]] = {k: [] for k in KINDS}

        for item in items:
            duration = None
            if item["start_date"]:
                duration = months_between(item["start_date"], item["end_date"] or today)
            window = "%s -> %s" % (item["start_date"] or "?", item["end_date"] or "ongoing")
            metrics.append({
                "id": "intervention-%s-%s" % (item["kind"], slugify(item["name"])),
                "record_type": "Intervention",
                "source_id": SOURCE_ID,
                "title": "%s (%s)" % (item["name"], item["kind"]),
                "summary": "%s, %s, %s.%s" % (
                    item["name"],
                    item["status"],
                    window,
                    " Dose: %s." % item["dose"] if item["dose"] else "",
                ),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 0.9,
                "date": item["start_date"],
                "start_date": item["start_date"],
                "end_date": item["end_date"],
                "tags": ["medications", item["kind"], item["status"]],
                "metadata": {
                    "kind": item["kind"],
                    "dose": item["dose"],
                    "schedule": item["schedule"],
                    "source": item["source"],
                    "reason": item["reason"],
                    "behavior_id": item["behavior_id"],
                    "duration_months": duration,
                },
                "intervention_kind": _intervention_kind(item["kind"]),
                "subject": item["name"],
                "status": item["status"],
                "dosage": item["dose"],
                "cadence": item["schedule"],
            })
            if item["status"] == "active":
                active_by_kind[item["kind"]].append(
                    {"name": item["name"], "dose": item["dose"], "duration_months": duration}
                )

            # Long-running active med/supplement -> a C3 question, not advice.
            if (
                item["status"] == "active"
                and item["kind"] in ("medication", "supplement")
                and duration is not None
                and duration >= review_months
            ):
                conf = evidence.Confidence.C3
                txt = (
                    "%s has been active for about %.1f months (since %s). A periodic review with the "
                    "prescribing clinician may be due" % (item["name"], duration, item["start_date"])
                )
                insights.append({
                    "id": "insight-medications-review-%s" % slugify(item["name"]),
                    "record_type": "InsightHypothesis",
                    "source_id": SOURCE_ID,
                    "title": "Review prompt: %s" % item["name"],
                    "summary": evidence.frame_statement(txt, conf),
                    "artifact_ids": [],
                    "evidence_class": "derived-hypothesis",
                    "confidence": evidence.confidence_to_numeric(conf),
                    "date": today,
                    "tags": ["medications", "review-needed", "see-clinician"],
                    "metadata": {"name": item["name"], "duration_months": duration, "threshold_months": review_months},
                    "statement": txt,
                    "evidence_record_ids": ["intervention-%s-%s" % (item["kind"], slugify(item["name"]))],
                    "open_questions": [
                        "Is the original reason still present?",
                        "Are dose and duration still right? (Only the prescriber can say.)",
                    ],
                })

        # Honest interaction note: 2+ active meds/supplements -> we do NOT check.
        active_pharma = active_by_kind["medication"] + active_by_kind["supplement"]
        if len(active_pharma) >= 2:
            names = ", ".join(x["name"] for x in active_pharma)
            insights.append({
                "id": "note-medications-interactions",
                "record_type": "ContextNote",
                "source_id": SOURCE_ID,
                "title": "Interaction check is a human job",
                "summary": (
                    "%d medications/supplements are active at once (%s). OpenHealth does not check drug or "
                    "supplement interactions - verify combinations with a doctor or pharmacist."
                    % (len(active_pharma), names)
                ),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 1.0,
                "date": today,
                "tags": ["medications", "interaction-check", "see-clinician"],
                "metadata": {"active_items": active_pharma},
                "note_kind": "medications_interaction_disclaimer",
                "themes": ["medications"],
            })

        # Habits -> journal behavior candidates so correlations can pick them up.
        habit_links: List[Dict[str, Any]] = []
        for item in items:
            if item["kind"] not in ("habit_bad", "habit_good"):
                continue
            behavior = catalog.resolve(item["behavior_id"] or item["name"])
            habit_links.append({
                "name": item["name"],
                "kind": item["kind"],
                "behavior_id": behavior["id"] if behavior else None,
                "matched": behavior is not None,
            })
        if habit_links:
            matched = [h for h in habit_links if h["matched"]]
            insights.append({
                "id": "note-medications-journal-links",
                "record_type": "ContextNote",
                "source_id": SOURCE_ID,
                "title": "Habits worth tracking in the journal",
                "summary": (
                    "%d habit(s) in the ledger; %d match a journal behavior. Tracking them daily lets the "
                    "correlations module test what actually affects recovery." % (len(habit_links), len(matched))
                ),
                "artifact_ids": [],
                "evidence_class": "personal",
                "confidence": 1.0,
                "date": today,
                "tags": ["medications", "journal-link", "correlations-candidate"],
                "metadata": {"candidates": habit_links},
                "note_kind": "medications_journal_link",
                "themes": ["medications", "journal"],
            })

        # Ledger snapshot for the UI / agent.
        counts = {k: len(v) for k, v in active_by_kind.items()}
        insights.append({
            "id": "note-medications-snapshot-%s" % today,
            "record_type": "ContextNote",
            "source_id": SOURCE_ID,
            "title": "Medication ledger snapshot %s" % today,
            "summary": "Active: %d medication(s), %d supplement(s), %d bad habit(s), %d good habit(s)." % (
                counts["medication"],
                counts["supplement"],
                counts["habit_bad"],
                counts["habit_good"],
            ),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 1.0,
            "date": today,
            "tags": ["medications", "snapshot"],
            "metadata": {"active": active_by_kind, "counts": counts, "total_items": len(items)},
            "note_kind": "medications_snapshot",
            "themes": ["medications"],
        })

        notes = ["medication ledger: %d item(s), %d active" % (
            len(items),
            sum(counts.values()),
        )]
        return ModuleResult(metrics=metrics, insights=insights, notes=notes)


def persist(result: ModuleResult, db_path) -> int:
    """Write ledger records + notes into the SQLite index; returns count."""
    from .. import index

    written = 0
    for rec in list(result.metrics) + list(result.insights):
        index.upsert_record(db_path, rec)
        written += 1
    return written


register(MedicationsModule())
