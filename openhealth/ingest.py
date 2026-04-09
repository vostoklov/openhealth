from pathlib import Path
from typing import Dict, List, Optional

from . import index
from .config import SOURCE_TYPES
from .contexts import build_source_brief, refresh_contexts
from .metadata import load_sidecar_metadata
from .models import ArtifactManifest, Observation, SourceManifest
from .parsers import parse_artifact
from .storage import (
    archive_artifact,
    discover_input_files,
    ensure_repo_structure,
    guess_mime_type,
    now_utc,
    sha256sum,
    slugify,
    write_json,
    write_text,
)
from .weather import WeatherEnricher


def init_workspace(root: Path) -> Dict[str, str]:
    paths = ensure_repo_structure(root)
    index.init_db(paths.db_path)
    refresh_contexts(paths, index)
    return {"root": str(paths.root), "db_path": str(paths.db_path)}


def ingest_path(
    root: Path,
    source_type: str,
    path: Path,
    owner: str = "user",
    label: Optional[str] = None,
    location: Optional[str] = None,
) -> Dict[str, object]:
    if source_type not in SOURCE_TYPES:
        raise ValueError("Unsupported source type: %s" % source_type)
    paths = ensure_repo_structure(root)
    index.init_db(paths.db_path)
    input_files = list(discover_input_files(path))
    if not input_files:
        raise ValueError("No input files found at %s" % path)

    source_id = "%s-%s-%s" % (
        source_type,
        slugify(label or path.stem),
        now_utc().replace(":", "").replace("+00:00", "z"),
    )
    artifacts: List[Dict] = []
    records: List[Dict] = []
    parser_notes: List[str] = []
    weather = WeatherEnricher(paths.weather_cache_path)
    weather_ids = set()
    skipped_duplicates = 0

    for file_path in input_files:
        checksum = sha256sum(file_path)
        duplicate = index.find_artifact_by_checksum(paths.db_path, checksum)
        if duplicate:
            skipped_duplicates += 1
            continue
        metadata = load_sidecar_metadata(file_path)
        if location and "location" not in metadata:
            metadata["location"] = location
        archived_path = archive_artifact(file_path, paths, source_type, checksum)
        artifact_id = "artifact-%s-%s" % (source_type, checksum[:12])
        artifact = ArtifactManifest(
            artifact_id=artifact_id,
            source_id=source_id,
            source_type=source_type,
            original_path=str(file_path),
            archived_path=str(archived_path),
            checksum=checksum,
            mime_type=guess_mime_type(file_path),
            size_bytes=file_path.stat().st_size,
            provenance={"ingested_at": now_utc(), "source_path": str(file_path)},
            privacy={"storage": "local-first", "shareable": False},
            metadata=metadata,
        )
        parsed_records, notes = parse_artifact(source_type, source_id, artifact_id, archived_path, metadata)
        parser_notes.extend(notes)
        artifacts.append(artifact.to_dict())
        for record in parsed_records:
            records.append(record)
            weather_payload = weather.enrich(record.get("date") or record.get("start_date"), record.get("location"))
            if weather_payload:
                weather_id = "obs-weather-%s-%s" % (
                    slugify(record.get("location") or "unknown"),
                    (record.get("date") or record.get("start_date")),
                )
                if weather_id in weather_ids:
                    continue
                weather_ids.add(weather_id)
                weather_record = Observation(
                    id=weather_id,
                    record_type="Observation",
                    source_id=source_id,
                    title="Weather context for %s" % (record.get("date") or record.get("start_date")),
                    summary="Weather context enriched for %s on %s." % (
                        record.get("location"),
                        record.get("date") or record.get("start_date"),
                    ),
                    artifact_ids=[artifact_id],
                    evidence_class="contextual",
                    confidence=0.6,
                    date=record.get("date") or record.get("start_date"),
                    location=record.get("location"),
                    tags=["weather", "enrichment"],
                    metadata=weather_payload,
                    observation_kind="weather_enrichment",
                    metric_name="weather_summary",
                    value=weather_payload,
                    unit=None,
                )
                records.append(weather_record.to_dict())

    coverage_dates = [record.get("date") or record.get("start_date") for record in records if record.get("date") or record.get("start_date")]
    coverage_start = min(coverage_dates) if coverage_dates else None
    coverage_end = max(coverage_dates) if coverage_dates else None
    parser_status = "duplicate-skip" if not artifacts and skipped_duplicates else ("parsed" if artifacts else "empty")
    source = SourceManifest(
        source_id=source_id,
        source_type=source_type,
        owner=owner,
        label=label or path.stem,
        created_at=now_utc(),
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        files=[str(file_path) for file_path in input_files],
        parser_status=parser_status,
        notes=parser_notes + (["Skipped duplicate artifacts: %s" % skipped_duplicates] if skipped_duplicates else []),
        metadata={"location": location} if location else {},
    )

    if artifacts:
        write_json(paths.source_manifests / ("%s.json" % source_id), source.to_dict())
        index.upsert_source(paths.db_path, source.to_dict())
        for artifact in artifacts:
            write_json(paths.artifact_manifests / ("%s.json" % artifact["artifact_id"]), artifact)
            index.upsert_artifact(paths.db_path, artifact)
        for record in records:
            index.upsert_record(paths.db_path, record)
        write_json(paths.records / ("%s.json" % source_id), records)
    source_brief = build_source_brief(source.to_dict(), index.list_artifacts(paths.db_path), index.list_records(paths.db_path))
    write_text(paths.briefs / ("%s.md" % source_id), source_brief)
    context_stats = refresh_contexts(paths, index)
    return {
        "source_id": source_id,
        "source_type": source_type,
        "artifacts_imported": len(artifacts),
        "records_imported": len(records),
        "duplicates_skipped": skipped_duplicates,
        "coverage_start": coverage_start,
        "coverage_end": coverage_end,
        "contexts": context_stats,
    }
