"""Privacy utilities — strip PII and pseudonymize before anything is shared.

Personal health data is local-first and never leaves the machine by default.
When a user *opts in* to contribute an anonymized artifact (e.g. an aggregate to
a community hypothesis pool), it must pass through here first: drop PII-bearing
fields, blank free text, coarsen timestamps to a date, pseudonymize identifiers,
then validate that nothing obvious leaked. Pure stdlib.
"""

import hashlib
import re
from typing import Any, Dict, List, Tuple

# Fields that may directly carry personal information.
PII_FIELDS = (
    "location", "people", "author", "media_path", "comparison_target_id",
)
# Free-text fields whose contents we blank out (may embed names, places, notes).
FREE_TEXT_FIELDS = ("extracted_text", "body", "raw_row", "notes", "caption", "attachments")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE = re.compile(r"(?<!\d)(\+?\d[\d\s().-]{7,}\d)(?!\d)")


def pseudonymize(identifier: str, salt: str) -> str:
    """Stable, non-reversible pseudonym for an identifier under a given salt."""
    h = hashlib.sha256(("%s::%s" % (salt, identifier)).encode("utf-8")).hexdigest()
    return "p_" + h[:16]


def _coarsen_timestamp(value: str) -> str:
    """Keep the date, drop the time (reduces re-identification by exact moment)."""
    return value[:10] if isinstance(value, str) and len(value) >= 10 else value


def strip_pii(record: Dict[str, Any]) -> Dict[str, Any]:
    """Return a copy with PII fields removed and free text blanked."""
    out: Dict[str, Any] = {}
    for k, v in record.items():
        if k in PII_FIELDS:
            continue
        if k in FREE_TEXT_FIELDS:
            continue
        if k in ("captured_at",) and isinstance(v, str):
            out[k] = _coarsen_timestamp(v)
            continue
        if k == "metadata" and isinstance(v, dict):
            out[k] = {
                mk: mv for mk, mv in v.items()
                if mk not in PII_FIELDS and mk not in FREE_TEXT_FIELDS
            }
            continue
        out[k] = v
    return out


def anonymize_for_share(record: Dict[str, Any], salt: str) -> Dict[str, Any]:
    """Strip PII then pseudonymize owner/source identifiers."""
    out = strip_pii(record)
    for key in ("source_id", "owner"):
        if out.get(key):
            out[key] = pseudonymize(str(out[key]), salt)
    return out


# Human-readable text fields where an email/phone could hide. We scan only
# these (not ids, hashes or numbers) to avoid false positives on pseudonyms.
_TEXT_FIELDS = ("title", "summary", "statement", "note", "caption")


def _text_values(record: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for k in _TEXT_FIELDS:
        v = record.get(k)
        if isinstance(v, str):
            out.append(v)
    meta = record.get("metadata")
    if isinstance(meta, dict):
        for v in meta.values():
            if isinstance(v, str):
                out.append(v)
    return out


def find_pii(record: Dict[str, Any]) -> List[str]:
    """Return reasons a record still looks like it carries PII (empty = clean)."""
    reasons: List[str] = []
    for f in PII_FIELDS:
        if record.get(f):
            reasons.append("field %r present" % f)
    for text in _text_values(record):
        if _EMAIL.search(text):
            reasons.append("text looks like an email address")
        if _PHONE.search(text):
            reasons.append("text looks like a phone number")
    return reasons


def is_anonymized(record: Dict[str, Any]) -> Tuple[bool, List[str]]:
    """(True, []) if the record passes the anonymization check, else (False, reasons)."""
    reasons = find_pii(record)
    return (len(reasons) == 0, reasons)
