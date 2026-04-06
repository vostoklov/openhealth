from dataclasses import dataclass
from pathlib import Path


SOURCE_TYPES = (
    "whoop",
    "document-tests",
    "messages",
    "telegram-posts",
    "manual-notes",
    "reference-examples",
    "product-usage",
    "image-observations",
    "telegram-intake",
)


SYSTEM_SOURCE_IDS = {"system-insights"}


@dataclass
class RepoPaths:
    root: Path
    raw_inbox: Path
    raw_archive: Path
    raw_archive_whoop_api: Path
    processed: Path
    source_manifests: Path
    artifact_manifests: Path
    records: Path
    briefs: Path
    contexts: Path
    timeline_context: Path
    interventions_context: Path
    data_index: Path
    db_path: Path
    weather_cache_path: Path
    whoop_tokens_path: Path
    whoop_sync_state_path: Path
    whoop_webhooks_path: Path
    schemas: Path
    docs: Path
    skills: Path


def build_paths(root: Path) -> RepoPaths:
    data_dir = root / "data"
    processed = data_dir / "processed"
    data_index = data_dir / "index"
    contexts = root / "contexts"
    return RepoPaths(
        root=root,
        raw_inbox=data_dir / "raw" / "inbox",
        raw_archive=data_dir / "raw" / "archive",
        raw_archive_whoop_api=data_dir / "raw" / "archive" / "whoop-api",
        processed=processed,
        source_manifests=processed / "manifests" / "sources",
        artifact_manifests=processed / "manifests" / "artifacts",
        records=processed / "records",
        briefs=processed / "briefs",
        contexts=contexts,
        timeline_context=contexts / "timeline",
        interventions_context=contexts / "interventions",
        data_index=data_index,
        db_path=data_index / "health_os.sqlite3",
        weather_cache_path=data_index / "weather_cache.json",
        whoop_tokens_path=data_index / "whoop_tokens.json",
        whoop_sync_state_path=data_index / "whoop_sync_state.json",
        whoop_webhooks_path=data_index / "whoop_webhooks.jsonl",
        schemas=root / "schemas",
        docs=root / "docs",
        skills=root / "skills",
    )
