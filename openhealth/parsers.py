import csv
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .metadata import coerce_list, parse_frontmatter, strip_frontmatter
from .models import (
    BodyZone,
    ContextNote,
    InsightHypothesis,
    IntakeEnvelope,
    Intervention,
    MediaObservation,
    Observation,
    PatternAlert,
    ReferenceCase,
    TimelineEvent,
)
from .storage import now_utc, slugify


TEXT_EXTENSIONS = {".txt", ".md", ".json", ".csv"}


def parse_artifact(
    source_type: str,
    source_id: str,
    artifact_id: str,
    archived_path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    if source_type == "whoop":
        return parse_whoop(source_id, artifact_id, archived_path, metadata)
    if source_type == "document-tests":
        return parse_document(source_id, artifact_id, archived_path, metadata)
    if source_type in {"messages", "telegram-posts", "manual-notes"}:
        return parse_context_text(source_type, source_id, artifact_id, archived_path, metadata)
    if source_type == "reference-examples":
        return parse_reference_case(source_id, artifact_id, archived_path, metadata)
    if source_type == "product-usage":
        return parse_intervention(source_id, artifact_id, archived_path, metadata)
    if source_type == "image-observations":
        return parse_image_observation(source_id, artifact_id, archived_path, metadata)
    if source_type == "telegram-intake":
        return parse_telegram_envelope(source_id, artifact_id, archived_path, metadata)
    return parse_document(source_id, artifact_id, archived_path, metadata)


def extract_text(path: Path) -> Optional[str]:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return path.read_text(encoding="utf-8", errors="ignore")
    if path.suffix.lower() == ".pdf":
        try:
            output = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
            )
            return output.stdout
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None
    return None


def parse_whoop(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    parser_notes: List[str] = []
    rows = _load_structured_rows(path)
    records: List[Dict[str, Any]] = []
    numeric_fields: List[str] = []
    for index, row in enumerate(rows):
        date_value = _pick_first(row, ["date", "Date", "day", "Day", "start", "Start"])
        if not date_value:
            parser_notes.append("Skipped row %s because no date column was found." % index)
            continue
        if not numeric_fields:
            numeric_fields = [
                key
                for key, value in row.items()
                if key.lower() not in {"date", "day", "start", "end", "timezone"}
                and _is_number(value)
            ]
        event_id = "event-%s-%03d" % (source_id, index + 1)
        event_summary_parts: List[str] = []
        for field in numeric_fields:
            raw_value = row.get(field)
            if not _is_number(raw_value):
                continue
            metric_slug = slugify(field)
            metric_id = "obs-%s-%03d-%s" % (source_id, index + 1, metric_slug)
            numeric_value = float(raw_value)
            event_summary_parts.append("%s=%s" % (field, raw_value))
            observation = Observation(
                id=metric_id,
                record_type="Observation",
                source_id=source_id,
                title="Whoop %s" % field,
                summary="Whoop metric %s recorded on %s." % (field, date_value),
                artifact_ids=[artifact_id],
                evidence_class="personal",
                confidence=0.98,
                date=str(date_value),
                tags=["whoop", metric_slug],
                metadata={"raw_row": row},
                observation_kind="whoop_metric",
                metric_name=field,
                value=numeric_value,
                unit=_infer_unit(field),
            )
            records.append(observation.to_dict())
        event = TimelineEvent(
            id=event_id,
            record_type="TimelineEvent",
            source_id=source_id,
            title="Whoop daily snapshot",
            summary="; ".join(event_summary_parts[:5]) or "Whoop daily snapshot.",
            artifact_ids=[artifact_id],
            evidence_class="personal",
            confidence=0.95,
            date=str(date_value),
            location=metadata.get("location"),
            tags=["whoop", "daily-snapshot"],
            metadata={"raw_row": row},
            event_kind="measurement_day",
            related_record_ids=[record["id"] for record in records if record["source_id"] == source_id][-len(event_summary_parts) :],
        )
        records.append(event.to_dict())
    return records, parser_notes


def parse_document(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    parser_notes: List[str] = []
    text = extract_text(path)
    frontmatter = parse_frontmatter(text or "")
    merged = _merge_metadata(metadata, frontmatter)
    text_body = strip_frontmatter(text or "") if text else ""
    summary = merged.get("summary") or _summarize_text(text_body) or "Binary artifact archived for later review."
    confidence = 0.65 if text_body else 0.2
    if not text_body:
        parser_notes.append("No inline text extraction available; summary relies on metadata or placeholder text.")
    records: List[Dict[str, Any]] = []
    note = ContextNote(
        id="note-%s-doc" % source_id,
        record_type="ContextNote",
        source_id=source_id,
        title=merged.get("title") or path.stem.replace("-", " ").title(),
        summary=summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=confidence,
        date=merged.get("date"),
        start_date=merged.get("start_date"),
        end_date=merged.get("end_date"),
        location=merged.get("location"),
        tags=coerce_list(merged.get("tags")) + ["document-test"],
        metadata={"extracted_text": text_body[:4000], "source_kind": "document-tests"},
        note_kind=merged.get("note_kind", "test_report"),
        themes=coerce_list(merged.get("themes")),
    )
    records.append(note.to_dict())
    for index, observation in enumerate(merged.get("observations", [])):
        record = Observation(
            id="obs-%s-doc-%02d" % (source_id, index + 1),
            record_type="Observation",
            source_id=source_id,
            title=observation.get("title") or observation.get("metric_name", "Document observation"),
            summary=observation.get("summary") or summary,
            artifact_ids=[artifact_id],
            evidence_class="personal",
            confidence=float(observation.get("confidence", confidence)),
            date=observation.get("date") or merged.get("date"),
            tags=coerce_list(observation.get("tags")) + ["document-test"],
            metadata={"source_kind": "document-tests"},
            observation_kind=observation.get("observation_kind", "test_result"),
            metric_name=observation.get("metric_name"),
            value=observation.get("value"),
            unit=observation.get("unit"),
        )
        records.append(record.to_dict())
    if merged.get("date") or merged.get("start_date"):
        event = TimelineEvent(
            id="event-%s-doc" % source_id,
            record_type="TimelineEvent",
            source_id=source_id,
            title=note.title,
            summary=summary,
            artifact_ids=[artifact_id],
            evidence_class="personal",
            confidence=confidence,
            date=merged.get("date"),
            start_date=merged.get("start_date"),
            end_date=merged.get("end_date"),
            location=merged.get("location"),
            tags=note.tags,
            metadata={"source_kind": "document-tests"},
            event_kind="document_review",
            related_record_ids=[record["id"] for record in records if record["record_type"] == "Observation"],
        )
        records.append(event.to_dict())
    return records, parser_notes


def parse_context_text(
    source_type: str,
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    text = extract_text(path) or ""
    frontmatter = parse_frontmatter(text)
    merged = _merge_metadata(metadata, frontmatter)
    body = strip_frontmatter(text)
    title = merged.get("title") or path.stem.replace("-", " ").title()
    summary = merged.get("summary") or _summarize_text(body) or title
    note = ContextNote(
        id="note-%s-main" % source_id,
        record_type="ContextNote",
        source_id=source_id,
        title=title,
        summary=summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=0.8,
        date=merged.get("date"),
        start_date=merged.get("start_date"),
        end_date=merged.get("end_date"),
        location=merged.get("location"),
        tags=coerce_list(merged.get("tags")) + [source_type],
        metadata={"body": body[:8000], "source_kind": source_type},
        note_kind=merged.get("note_kind", source_type.replace("-", "_")),
        people=coerce_list(merged.get("people")),
        themes=coerce_list(merged.get("themes")),
        mood=merged.get("mood"),
    )
    records = [note.to_dict()]
    if note.date or note.start_date:
        event = TimelineEvent(
            id="event-%s-main" % source_id,
            record_type="TimelineEvent",
            source_id=source_id,
            title=title,
            summary=summary,
            artifact_ids=[artifact_id],
            evidence_class="personal",
            confidence=0.78,
            date=note.date,
            start_date=note.start_date,
            end_date=note.end_date,
            location=note.location,
            tags=note.tags,
            metadata={"source_kind": source_type},
            event_kind="context_note",
            related_record_ids=[note.id],
        )
        records.append(event.to_dict())
    return records, []


def parse_reference_case(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    text = extract_text(path) or ""
    frontmatter = parse_frontmatter(text)
    merged = _merge_metadata(metadata, frontmatter)
    body = strip_frontmatter(text)
    record = ReferenceCase(
        id="ref-%s-main" % source_id,
        record_type="ReferenceCase",
        source_id=source_id,
        title=merged.get("title") or path.stem.replace("-", " ").title(),
        summary=merged.get("summary") or _summarize_text(body) or "External reference case.",
        artifact_ids=[artifact_id],
        evidence_class="external-reference",
        confidence=0.55,
        date=merged.get("date"),
        tags=coerce_list(merged.get("tags")) + ["reference-case"],
        metadata={"body": body[:8000]},
        origin=merged.get("origin"),
        applicability=merged.get("applicability"),
        external_links=coerce_list(merged.get("external_links")),
    )
    return [record.to_dict()], []


def parse_intervention(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    text = extract_text(path) or ""
    frontmatter = parse_frontmatter(text)
    merged = _merge_metadata(metadata, frontmatter)
    body = strip_frontmatter(text)
    title = merged.get("title") or merged.get("subject") or path.stem.replace("-", " ").title()
    summary = merged.get("summary") or _summarize_text(body) or "%s tracked as intervention." % title
    intervention = Intervention(
        id="int-%s-main" % source_id,
        record_type="Intervention",
        source_id=source_id,
        title=title,
        summary=summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=0.82,
        date=merged.get("date"),
        start_date=merged.get("start_date") or merged.get("date"),
        end_date=merged.get("end_date"),
        location=merged.get("location"),
        tags=coerce_list(merged.get("tags")) + ["intervention"],
        metadata={"body": body[:4000], "products": merged.get("products")},
        intervention_kind=merged.get("intervention_kind", "routine"),
        subject=merged.get("subject") or title,
        status=merged.get("status", "active"),
        dosage=merged.get("dosage"),
        cadence=merged.get("cadence"),
    )
    records = [intervention.to_dict()]
    event = TimelineEvent(
        id="event-%s-intervention" % source_id,
        record_type="TimelineEvent",
        source_id=source_id,
        title=title,
        summary=summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=0.8,
        date=merged.get("date"),
        start_date=intervention.start_date,
        end_date=intervention.end_date,
        location=intervention.location,
        tags=intervention.tags,
        metadata={"source_kind": "product-usage"},
        event_kind="intervention",
        related_record_ids=[intervention.id],
    )
    records.append(event.to_dict())
    return records, []


def parse_image_observation(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    parser_notes: List[str] = []
    body_zone = metadata.get("body_zone", "custom")
    visible_attrs = coerce_list(metadata.get("visible_attributes"))
    severity = metadata.get("severity")
    side = metadata.get("side")

    # Validate body zone
    valid_zones = {z.value for z in BodyZone}
    if body_zone not in valid_zones:
        parser_notes.append("Unknown body zone '%s', defaulting to 'custom'." % body_zone)
        body_zone = "custom"

    summary = metadata.get("summary") or "Image observation of %s zone." % body_zone
    if visible_attrs:
        summary += " Visible: %s." % ", ".join(visible_attrs)
    if severity:
        summary += " Severity: %s." % severity

    observation = MediaObservation(
        id="media-%s-image" % source_id,
        record_type="MediaObservation",
        source_id=source_id,
        title=metadata.get("title") or "%s observation" % body_zone.capitalize(),
        summary=summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=float(metadata.get("confidence", 0.45)),
        date=metadata.get("date"),
        location=metadata.get("location"),
        tags=coerce_list(metadata.get("tags")) + ["image-observation", "body-zone-%s" % body_zone],
        metadata={"observation_target": metadata.get("observation_target")},
        body_zone=body_zone,
        side=side,
        visible_attributes=visible_attrs,
        severity=severity,
        comparison_target_id=metadata.get("comparison_target_id"),
        media_path=str(path),
    )
    records: List[Dict[str, Any]] = [observation.to_dict()]

    if metadata.get("date"):
        event = TimelineEvent(
            id="event-%s-image" % source_id,
            record_type="TimelineEvent",
            source_id=source_id,
            title=observation.title,
            summary=summary,
            artifact_ids=[artifact_id],
            evidence_class="personal",
            confidence=0.4,
            date=metadata.get("date"),
            tags=observation.tags,
            metadata={"body_zone": body_zone},
            event_kind="media_observation",
            related_record_ids=[observation.id],
        )
        records.append(event.to_dict())

    if not visible_attrs:
        parser_notes.append("Image stored without visual attribute tags. Add body_zone and visible_attributes to metadata for richer tracking.")
    return records, parser_notes


def parse_telegram_envelope(
    source_id: str,
    artifact_id: str,
    path: Path,
    metadata: Dict[str, Any],
) -> Tuple[List[Dict[str, Any]], List[str]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    envelope = IntakeEnvelope(
        submission_id=payload["submission_id"],
        submitted_at=payload["submitted_at"],
        channel=payload.get("channel", "telegram"),
        author=payload.get("author", "unknown"),
        text=payload.get("text"),
        location=payload.get("location"),
        attachments=payload.get("attachments", []),
        tags=payload.get("tags", []),
        metadata=payload.get("metadata", {}),
    )
    summary = envelope.text or "Telegram intake with %s attachment(s)." % len(envelope.attachments)
    note = ContextNote(
        id="note-%s-envelope" % source_id,
        record_type="ContextNote",
        source_id=source_id,
        title="Telegram intake %s" % envelope.submission_id,
        summary=_summarize_text(summary) or summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=0.72,
        captured_at=envelope.submitted_at,
        date=payload.get("date") or envelope.submitted_at[:10],
        location=envelope.location,
        tags=envelope.tags + ["telegram-intake"],
        metadata=envelope.to_dict(),
        note_kind="telegram_intake",
        themes=coerce_list(payload.get("themes")),
    )
    records: List[Dict[str, Any]] = [note.to_dict()]

    # Create MediaObservation for photo attachments with body zone info
    for idx, attachment in enumerate(envelope.attachments):
        if attachment.get("type") in ("photo", "image"):
            body_zone = attachment.get("body_zone", "custom")
            valid_zones = {z.value for z in BodyZone}
            if body_zone not in valid_zones:
                body_zone = "custom"
            visible_attrs = coerce_list(attachment.get("visible_attributes"))
            media_obs = MediaObservation(
                id="media-%s-att-%02d" % (source_id, idx),
                record_type="MediaObservation",
                source_id=source_id,
                title="%s photo via Telegram" % body_zone.capitalize(),
                summary=attachment.get("caption") or "Photo of %s zone." % body_zone,
                artifact_ids=[artifact_id],
                evidence_class="personal",
                confidence=0.5,
                captured_at=envelope.submitted_at,
                date=note.date,
                location=envelope.location,
                tags=["telegram-intake", "body-zone-%s" % body_zone],
                body_zone=body_zone,
                side=attachment.get("side"),
                visible_attributes=visible_attrs,
                severity=attachment.get("severity"),
                media_path=attachment.get("file_path"),
            )
            records.append(media_obs.to_dict())

    event = TimelineEvent(
        id="event-%s-envelope" % source_id,
        record_type="TimelineEvent",
        source_id=source_id,
        title=note.title,
        summary=note.summary,
        artifact_ids=[artifact_id],
        evidence_class="personal",
        confidence=0.7,
        captured_at=note.captured_at,
        date=note.date,
        location=note.location,
        tags=note.tags,
        metadata={"attachment_count": len(envelope.attachments)},
        event_kind="telegram_submission",
        related_record_ids=[r["id"] for r in records],
    )
    records.append(event.to_dict())
    return records, []


def derive_insights(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {}
    for record in records:
        date_value = record.get("date") or record.get("start_date")
        if not date_value:
            continue
        grouped.setdefault(date_value, []).append(record)
    insights: List[Dict[str, Any]] = []
    for index, date_value in enumerate(sorted(grouped.keys())):
        day_records = grouped[date_value]
        interventions = [record for record in day_records if record["record_type"] == "Intervention"]
        observations = [record for record in day_records if record["record_type"] == "Observation"]
        notes = [record for record in day_records if record["record_type"] == "ContextNote"]
        if interventions and observations:
            statement = (
                "Intervention activity and measured signals overlap on %s. This is a correlation prompt, not a causal conclusion."
                % date_value
            )
            questions = ["Did the intervention start before the signal changed?", "Were there other simultaneous stressors or routines?"]
        elif notes and observations:
            statement = (
                "Context notes and measurements coexist on %s. Review the surrounding period for possible environmental or behavioral explanations."
                % date_value
            )
            questions = ["Is the note describing a transient event or an ongoing condition?", "Do nearby dates show the same pattern?"]
        else:
            continue
        insight = InsightHypothesis(
            id="insight-%03d" % (index + 1),
            record_type="InsightHypothesis",
            source_id="system-insights",
            title="Hypothesis for %s" % date_value,
            summary=statement,
            artifact_ids=[],
            evidence_class="derived-hypothesis",
            confidence=0.35,
            date=date_value,
            tags=["hypothesis", "review-needed"],
            metadata={},
            statement=statement,
            evidence_record_ids=[record["id"] for record in day_records[:6]],
            open_questions=questions,
        )
        insights.append(insight.to_dict())
    return insights[:5]


def _load_structured_rows(path: Path) -> List[Dict[str, Any]]:
    if path.suffix.lower() == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in ("records", "days", "data"):
                value = payload.get(key)
                if isinstance(value, list):
                    return value
        return []
    with path.open("r", encoding="utf-8", errors="ignore") as handle:
        reader = csv.DictReader(handle)
        return list(reader)


def _summarize_text(text: str) -> str:
    clean = " ".join(text.split())
    if not clean:
        return ""
    return clean[:280] + ("..." if len(clean) > 280 else "")


def _pick_first(row: Dict[str, Any], candidates: List[str]) -> Optional[str]:
    for key in candidates:
        value = row.get(key)
        if value:
            return str(value)
    return None


def _is_number(value: Any) -> bool:
    try:
        float(value)
        return True
    except (TypeError, ValueError):
        return False


def _infer_unit(field_name: str) -> Optional[str]:
    lowered = field_name.lower()
    if "sleep" in lowered:
        return "hours"
    if "recovery" in lowered or "%" in lowered:
        return "%"
    return None


def _merge_metadata(primary: Dict[str, Any], secondary: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(secondary)
    merged.update(primary)
    return merged
