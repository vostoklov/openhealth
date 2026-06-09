"""Medical document intake — discharge summaries, doctor recommendations, scans.

This is *intake only*: a dropped file (PDF / photo / text) is copied verbatim
into ``<root>/data/sources/medical/``, made read-only, and described by a
manifest entry plus a per-file ``.sidecar.json``. The content is deliberately
NOT parsed here — extraction is a separate, agent-driven step that reads the
archived copy on demand. That keeps the core rule intact: raw stays immutable,
``facts`` / ``extractions`` / ``hypotheses`` stay separated.

For doctor advice that arrives without a file ("the cardiologist said to
re-check ferritin in 3 months"), ``doctor_note`` builds a canonical
``ContextNote`` record that flows into the same SQLite index as everything
else; ``persist_record`` writes it.

Nothing here is medical advice. Pure stdlib, zero external deps (core rule).
"""

import hashlib
import json
import shutil
import stat
from datetime import date as _date
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .storage import guess_mime_type, sha256sum, slugify, write_json

SOURCE_ID = "medical-intake"

DOC_TYPES = ("discharge", "recommendation", "prescription", "exam", "other")

MANIFEST_VERSION = 1
MANIFEST_NAME = "manifest.json"


# --- paths & manifest --------------------------------------------------------


def medical_dir(root: Path) -> Path:
    """Where archived medical documents live: ``<root>/data/sources/medical``."""
    return Path(root) / "data" / "sources" / "medical"


def _manifest_path(root: Path) -> Path:
    return medical_dir(root) / MANIFEST_NAME


def load_manifest(root: Path) -> Dict[str, Any]:
    path = _manifest_path(root)
    if not path.exists():
        return {"version": MANIFEST_VERSION, "documents": []}
    return json.loads(path.read_text(encoding="utf-8"))


def _save_manifest(root: Path, manifest: Dict[str, Any]) -> None:
    write_json(_manifest_path(root), manifest)


def _now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _valid_date(value: str) -> str:
    # Raises ValueError on a malformed date (core rule: do not invent dates).
    _date.fromisoformat(value)
    return value


# --- document intake ---------------------------------------------------------


def ingest_medical_doc(
    root: Path,
    path: Path,
    doc_type: str,
    note: Optional[str] = None,
    date: Optional[str] = None,
    doctor: Optional[str] = None,
) -> Dict[str, Any]:
    """Archive one medical document (PDF / photo / text) and record provenance.

    Returns the manifest entry. Re-ingesting the same content (same checksum)
    is a no-op that returns the existing entry with ``duplicate: True``. The
    archived copy is chmod'ed read-only so casual edits fail loudly (raw stays
    immutable). Content is not parsed — that is a later, explicit agent step.
    """
    if doc_type not in DOC_TYPES:
        raise ValueError("unknown doc_type %r; expected one of %s" % (doc_type, ", ".join(DOC_TYPES)))
    src = Path(path)
    if not src.is_file():
        raise ValueError("no file at %s" % src)
    if date is not None:
        date = _valid_date(date)

    checksum = sha256sum(src)
    manifest = load_manifest(root)
    for entry in manifest["documents"]:
        if entry["checksum"] == checksum:
            existing = dict(entry)
            existing["duplicate"] = True
            return existing

    target_dir = medical_dir(root)
    target_dir.mkdir(parents=True, exist_ok=True)
    # Naming convention: <date>-<type>-<original-slug>-<checksum8><ext>
    day = date or datetime.now(timezone.utc).date().isoformat()
    archived_name = "%s-%s-%s-%s%s" % (day, doc_type, slugify(src.stem), checksum[:8], src.suffix.lower())
    archived_path = target_dir / archived_name
    if not archived_path.exists():
        shutil.copy2(src, archived_path)
        archived_path.chmod(stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # read-only: raw stays immutable

    entry = {
        "id": "meddoc-%s" % checksum[:12],
        "type": doc_type,
        "date": date,
        "doctor": doctor,
        "note": note,
        "original_path": str(src),
        "archived_path": str(archived_path),
        "checksum": checksum,
        "mime_type": guess_mime_type(src),
        "size_bytes": src.stat().st_size,
        "ingested_at": _now_utc(),
        "parsed": False,  # extraction is a separate agent step, never done at intake
    }
    sidecar = dict(entry)
    sidecar["provenance"] = {"source_id": SOURCE_ID, "ingested_at": entry["ingested_at"], "source_path": str(src)}
    sidecar["privacy"] = {"storage": "local-first", "shareable": False}
    write_json(archived_path.with_name(archived_path.name + ".sidecar.json"), sidecar)

    manifest["documents"].append(entry)
    _save_manifest(root, manifest)
    result = dict(entry)
    result["duplicate"] = False
    return result


def list_medical(
    root: Path,
    doc_type: Optional[str] = None,
    doctor: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Manifest entries, newest first, optionally filtered by type / doctor."""
    if doc_type is not None and doc_type not in DOC_TYPES:
        raise ValueError("unknown doc_type %r; expected one of %s" % (doc_type, ", ".join(DOC_TYPES)))
    docs = load_manifest(root)["documents"]
    if doc_type is not None:
        docs = [d for d in docs if d["type"] == doc_type]
    if doctor is not None:
        wanted = doctor.strip().lower()
        docs = [d for d in docs if (d.get("doctor") or "").strip().lower() == wanted]
    return sorted(docs, key=lambda d: d["ingested_at"], reverse=True)


# --- doctor recommendations without a file -----------------------------------


def doctor_note(
    text: str,
    date: str,
    doctor: Optional[str] = None,
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """A doctor's verbal recommendation as a canonical ``ContextNote`` dict.

    The note records *what was said*, not whether it is right — confidence is
    about provenance (it came from a clinician), and the system still never
    turns it into instructions of its own.
    """
    body = (text or "").strip()
    if not body:
        raise ValueError("doctor_note needs non-empty text")
    date = _valid_date(date)
    digest = hashlib.sha256(body.encode("utf-8")).hexdigest()[:8]
    return {
        "id": "doctor-note-%s-%s" % (date, digest),
        "record_type": "ContextNote",
        "source_id": SOURCE_ID,
        "title": "Doctor recommendation%s" % (" (%s)" % doctor if doctor else ""),
        "summary": body,
        "artifact_ids": [],
        "evidence_class": "personal",
        "confidence": 0.7,  # C4-grade provenance: stated by a clinician, still confirm details with them
        "date": date,
        "tags": sorted(set(["medical", "doctor", "recommendation"] + list(tags or []))),
        "metadata": {"doctor": doctor, "origin": "doctor", "verbatim": body},
        "note_kind": "doctor_recommendation",
        "themes": ["medical"],
    }


def persist_record(record: Dict[str, Any], db_path: Path) -> None:
    """Write one canonical record (e.g. a doctor note) into the SQLite index."""
    from . import index

    index.upsert_record(db_path, record)
