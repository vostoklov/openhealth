import hashlib
import json
import mimetypes
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable

from .config import RepoPaths, build_paths


def now_utc() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered)
    lowered = re.sub(r"-{2,}", "-", lowered).strip("-")
    return lowered or "item"


def ensure_repo_structure(root: Path) -> RepoPaths:
    paths = build_paths(root)
    for directory in (
        paths.raw_inbox,
        paths.raw_archive,
        paths.source_manifests,
        paths.artifact_manifests,
        paths.records,
        paths.briefs,
        paths.timeline_context,
        paths.interventions_context,
        paths.data_index,
        paths.schemas,
        paths.docs,
        paths.skills,
    ):
        directory.mkdir(parents=True, exist_ok=True)
    keep = paths.raw_archive / ".gitkeep"
    if not keep.exists():
        keep.write_text("", encoding="utf-8")
    return paths


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.rstrip() + "\n", encoding="utf-8")


def sha256sum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def guess_mime_type(path: Path) -> str:
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"


def archive_artifact(path: Path, paths: RepoPaths, source_type: str, checksum: str) -> Path:
    target_dir = paths.raw_archive / source_type / checksum[:8]
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / path.name
    if not target_path.exists():
        shutil.copy2(path, target_path)
    return target_path


def discover_input_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        return [path]
    return sorted(
        candidate
        for candidate in path.rglob("*")
        if candidate.is_file() and not candidate.name.endswith(".meta.json")
    )
