import json
import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.error import HTTPError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .. import index
from ..contexts import build_source_brief, refresh_contexts
from ..models import ArtifactManifest, Observation, SourceManifest, TimelineEvent
from ..storage import ensure_repo_structure, load_json_if_exists, now_utc, sha256sum, slugify, write_json, write_text

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_CALENDAR_API = "https://www.googleapis.com/calendar/v3"
GOOGLE_CALENDAR_SOURCE_ID = "google-calendar-sync"
DEFAULT_GOOGLE_SCOPES = (
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.events",
)


class GoogleCalendarError(RuntimeError):
    """Raised when Google Calendar configuration or API calls fail."""


@dataclass
class GoogleCalendarCredentials:
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: Tuple[str, ...] = DEFAULT_GOOGLE_SCOPES


class GoogleCalendarClient:
    def __init__(self, credentials: GoogleCalendarCredentials, tokens: Dict[str, Any]):
        self.credentials = credentials
        self.tokens = tokens

    def calendar_list(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token = None
        while True:
            payload = self._get("/users/me/calendarList", {"pageToken": page_token})
            items.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return items

    def list_events(self, calendar_id: str, time_min: str, time_max: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        page_token = None
        while True:
            payload = self._get(
                "/calendars/%s/events" % quote(calendar_id, safe=""),
                {
                    "timeMin": time_min,
                    "timeMax": time_max,
                    "singleEvents": "true",
                    "showDeleted": "false",
                    "orderBy": "startTime",
                    "pageToken": page_token,
                },
            )
            items.extend(payload.get("items", []))
            page_token = payload.get("nextPageToken")
            if not page_token:
                break
        return items

    def create_calendar(self, summary: str, description: str, time_zone: str) -> Dict[str, Any]:
        return self._post(
            "/calendars",
            {
                "summary": summary,
                "description": description,
                "timeZone": time_zone,
            },
        )

    def upsert_event(self, calendar_id: str, event_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        encoded_calendar = quote(calendar_id, safe="")
        encoded_event = quote(event_id, safe="")
        try:
            self._get("/calendars/%s/events/%s" % (encoded_calendar, encoded_event))
        except GoogleCalendarError as exc:
            if "404" not in str(exc):
                raise
            body = dict(payload)
            body["id"] = event_id
            return self._post("/calendars/%s/events" % encoded_calendar, body)
        return self._put("/calendars/%s/events/%s" % (encoded_calendar, encoded_event), payload)

    def delete_event(self, calendar_id: str, event_id: str) -> None:
        self._delete("/calendars/%s/events/%s" % (quote(calendar_id, safe=""), quote(event_id, safe="")))

    def _get(self, path: str, query: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        url = GOOGLE_CALENDAR_API + path
        if query:
            filtered = {key: value for key, value in query.items() if value not in (None, "")}
            if filtered:
                url += "?" + urlencode(filtered)
        return _google_request_json("GET", url, self.tokens["access_token"])

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return _google_request_json("POST", GOOGLE_CALENDAR_API + path, self.tokens["access_token"], payload)

    def _put(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        return _google_request_json("PUT", GOOGLE_CALENDAR_API + path, self.tokens["access_token"], payload)

    def _delete(self, path: str) -> None:
        _google_request_json("DELETE", GOOGLE_CALENDAR_API + path, self.tokens["access_token"])


def build_google_authorization_url(root: Path, state: str) -> Dict[str, Any]:
    credentials = load_google_credentials(root)
    query = urlencode(
        {
            "client_id": credentials.client_id,
            "redirect_uri": credentials.redirect_uri,
            "response_type": "code",
            "scope": " ".join(credentials.scopes),
            "access_type": "offline",
            "include_granted_scopes": "true",
            "prompt": "consent",
            "state": state,
        }
    )
    return {"authorization_url": "%s?%s" % (GOOGLE_AUTH_URL, query), "state": state}


def exchange_google_code(root: Path, code: str) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    credentials = load_google_credentials(root)
    payload = _google_token_request(
        {
            "code": code,
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "redirect_uri": credentials.redirect_uri,
            "grant_type": "authorization_code",
        }
    )
    normalized = _normalize_google_tokens(payload)
    write_json(paths.google_tokens_path, normalized)
    return {
        "token_path": str(paths.google_tokens_path),
        "expires_at": normalized["expires_at"],
        "scope": normalized.get("scope"),
    }


def load_google_credentials(root: Path) -> GoogleCalendarCredentials:
    paths = ensure_repo_structure(root)
    config = load_google_calendar_config(root)
    client_id = os.getenv(config["google_client_id_env"])
    client_secret = os.getenv(config["google_client_secret_env"])
    redirect_uri = os.getenv(config["google_redirect_uri_env"])
    missing = [
        env_name
        for env_name, value in (
            (config["google_client_id_env"], client_id),
            (config["google_client_secret_env"], client_secret),
            (config["google_redirect_uri_env"], redirect_uri),
        )
        if not value
    ]
    if missing:
        raise GoogleCalendarError("Missing Google Calendar credentials in environment: %s" % ", ".join(missing))
    _ = paths
    return GoogleCalendarCredentials(client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri)


def load_google_calendar_config(root: Path) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    config = load_json_if_exists(paths.google_calendar_config_path, {}) or {}
    if "derived_calendar" not in config:
        raise GoogleCalendarError("Google calendar config is missing derived_calendar.")
    return config


def save_google_calendar_config(root: Path, payload: Dict[str, Any]) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    write_json(paths.google_calendar_config_path, payload)
    return payload


def build_google_client(root: Path, client: Optional[Any] = None) -> Any:
    if client is not None:
        return client
    paths = ensure_repo_structure(root)
    credentials = load_google_credentials(root)
    tokens = ensure_google_tokens(paths.google_tokens_path, credentials)
    return GoogleCalendarClient(credentials, tokens)


def ensure_derived_calendar(root: Path, client: Optional[Any] = None) -> Dict[str, Any]:
    config = load_google_calendar_config(root)
    google_client = build_google_client(root, client=client)
    derived = dict(config.get("derived_calendar") or {})
    calendars = google_client.calendar_list()
    if derived.get("id"):
        for calendar in calendars:
            if calendar.get("id") == derived["id"]:
                return calendar
    for calendar in calendars:
        if calendar.get("summary") == derived.get("name"):
            derived["id"] = calendar["id"]
            config["derived_calendar"] = derived
            save_google_calendar_config(root, config)
            return calendar
    created = google_client.create_calendar(
        summary=derived["name"],
        description=derived.get("description") or "OpenHealth derived calendar.",
        time_zone=config.get("timezone") or "UTC",
    )
    derived["id"] = created["id"]
    config["derived_calendar"] = derived
    save_google_calendar_config(root, config)
    return created


def list_available_calendars(root: Path, client: Optional[Any] = None) -> Dict[str, Any]:
    google_client = build_google_client(root, client=client)
    calendars = google_client.calendar_list()
    return {
        "calendars": [
            {
                "id": item.get("id"),
                "summary": item.get("summary"),
                "primary": item.get("primary", False),
                "access_role": item.get("accessRole"),
                "selected": bool(item.get("selected", True)),
                "read_only": item.get("accessRole") == "reader",
            }
            for item in calendars
        ]
    }


def sync_google_calendar(
    root: Path,
    start: str,
    end: str,
    owner: str = "ilya",
    client: Optional[Any] = None,
) -> Dict[str, Any]:
    paths = ensure_repo_structure(root)
    index.init_db(paths.db_path)
    config = load_google_calendar_config(root)
    google_client = build_google_client(root, client=client)
    calendars = {item["id"]: item for item in google_client.calendar_list()}
    selected_ids = list(config.get("selected_calendar_ids") or [])
    if not selected_ids:
        primary = next((item["id"] for item in calendars.values() if item.get("primary")), None)
        if primary:
            selected_ids = [primary]
        elif calendars:
            selected_ids = [sorted(calendars.keys())[0]]
    sync_started_at = now_utc()
    sync_stamp = sync_started_at.replace(":", "").replace("+00:00", "z")

    artifacts: List[Dict[str, Any]] = []
    records: List[Dict[str, Any]] = []
    notes: List[str] = []
    grouped_by_day: Dict[str, Dict[str, Any]] = {}
    collection_counts: Dict[str, int] = {}

    for calendar_id in selected_ids:
        page_payload = {
            "calendar": calendars.get(calendar_id, {"id": calendar_id}),
            "items": google_client.list_events(calendar_id, time_min=start, time_max=end),
            "timeMin": start,
            "timeMax": end,
        }
        artifact = archive_google_calendar_payload(paths, calendar_id, sync_stamp, page_payload)
        artifacts.append(artifact)
        page_records, page_days = normalize_google_events(
            calendar=page_payload["calendar"],
            payload=page_payload,
            artifact_id=artifact["artifact_id"],
            source_id=GOOGLE_CALENDAR_SOURCE_ID,
        )
        records.extend(page_records)
        collection_counts[calendar_id] = len(page_payload["items"])
        for date_value, daily in page_days.items():
            grouped = grouped_by_day.setdefault(date_value, {"minutes": 0, "events": 0, "record_ids": []})
            grouped["minutes"] += daily["minutes"]
            grouped["events"] += daily["events"]
            grouped["record_ids"].extend(daily["record_ids"])

    for date_value, daily in sorted(grouped_by_day.items()):
        records.append(
            Observation(
                id="calendar-density-%s" % slugify(date_value),
                record_type="Observation",
                source_id=GOOGLE_CALENDAR_SOURCE_ID,
                title="Calendar load for %s" % date_value,
                summary="Calendar load imported from %s source calendar(s)." % len(selected_ids),
                artifact_ids=[artifact["artifact_id"] for artifact in artifacts],
                evidence_class="contextual",
                confidence=0.92,
                date=date_value,
                tags=["calendar", "schedule-density"],
                metadata={
                    "event_count": daily["events"],
                    "busy_minutes": daily["minutes"],
                    "selected_calendar_ids": selected_ids,
                },
                observation_kind="calendar_schedule_density",
                metric_name="busy_minutes",
                value=daily["minutes"],
                unit="minutes",
            ).to_dict()
        )
        records.append(
            Observation(
                id="calendar-event-count-%s" % slugify(date_value),
                record_type="Observation",
                source_id=GOOGLE_CALENDAR_SOURCE_ID,
                title="Calendar event count for %s" % date_value,
                summary="Number of imported calendar blocks for %s." % date_value,
                artifact_ids=[artifact["artifact_id"] for artifact in artifacts],
                evidence_class="contextual",
                confidence=0.92,
                date=date_value,
                tags=["calendar", "schedule-density"],
                metadata={"selected_calendar_ids": selected_ids},
                observation_kind="calendar_schedule_density",
                metric_name="event_count",
                value=daily["events"],
                unit="count",
            ).to_dict()
        )

    replaced_ids = purge_google_calendar_records(paths.db_path, start, end)
    for artifact in artifacts:
        write_json(paths.artifact_manifests / ("%s.json" % artifact["artifact_id"]), artifact)
        index.upsert_artifact(paths.db_path, artifact)
    for record in records:
        index.upsert_record(paths.db_path, record)

    coverage_points = [record.get("date") or record.get("start_date") for record in records if record.get("date") or record.get("start_date")]
    source = SourceManifest(
        source_id=GOOGLE_CALENDAR_SOURCE_ID,
        source_type="calendar",
        owner=owner,
        label="Google Calendar sync",
        created_at=sync_started_at,
        coverage_start=min(coverage_points) if coverage_points else start[:10],
        coverage_end=max(coverage_points) if coverage_points else end[:10],
        files=[artifact["archived_path"] for artifact in artifacts],
        parser_status="synced",
        notes=notes + ["Source calendars are treated as read-only. Derived events are written only to the derived calendar."],
        metadata={
            "selected_calendar_ids": selected_ids,
            "read_only_source_calendars": True,
            "derived_calendar_id": (config.get("derived_calendar") or {}).get("id"),
            "collections": collection_counts,
        },
    )
    write_json(paths.source_manifests / ("%s.json" % GOOGLE_CALENDAR_SOURCE_ID), source.to_dict())
    index.upsert_source(paths.db_path, source.to_dict())
    source_brief = build_source_brief(source.to_dict(), index.list_artifacts(paths.db_path), index.list_records(paths.db_path))
    write_text(paths.briefs / ("%s.md" % GOOGLE_CALENDAR_SOURCE_ID), source_brief)
    context_stats = refresh_contexts(paths, index)
    write_json(
        paths.google_calendar_sync_state_path,
        {
            "last_successful_sync": sync_started_at,
            "window_start": start,
            "window_end": end,
            "selected_calendar_ids": selected_ids,
            "replaced_record_ids": len(replaced_ids),
        },
    )
    return {
        "source_id": GOOGLE_CALENDAR_SOURCE_ID,
        "records_imported": len(records),
        "artifacts_archived": len(artifacts),
        "selected_calendar_ids": selected_ids,
        "replaced_record_ids": len(replaced_ids),
        "contexts": context_stats,
    }


def archive_google_calendar_payload(paths: Any, calendar_id: str, sync_stamp: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    target_dir = paths.raw_archive_calendar_api / sync_stamp / slugify(calendar_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / "events.json"
    write_json(target_path, payload)
    checksum = sha256sum(target_path)
    artifact = ArtifactManifest(
        artifact_id="artifact-gcal-%s" % checksum[:12],
        source_id=GOOGLE_CALENDAR_SOURCE_ID,
        source_type="calendar",
        original_path="gcal://%s/events" % calendar_id,
        archived_path=str(target_path),
        checksum=checksum,
        mime_type="application/json",
        size_bytes=target_path.stat().st_size,
        provenance={"ingested_at": now_utc(), "calendar_id": calendar_id},
        privacy={"storage": "local-first", "shareable": False},
        metadata={"calendar_id": calendar_id, "event_count": len(payload.get("items", []))},
    )
    return artifact.to_dict()


def normalize_google_events(
    calendar: Dict[str, Any],
    payload: Dict[str, Any],
    artifact_id: str,
    source_id: str,
) -> Tuple[List[Dict[str, Any]], Dict[str, Dict[str, Any]]]:
    records: List[Dict[str, Any]] = []
    grouped_by_day: Dict[str, Dict[str, Any]] = {}
    for item in payload.get("items", []):
        if item.get("status") == "cancelled":
            continue
        event_id = item.get("id") or slugify(item.get("summary") or "calendar-event")
        start_payload = item.get("start") or {}
        end_payload = item.get("end") or {}
        start_value = start_payload.get("dateTime") or start_payload.get("date")
        end_value = end_payload.get("dateTime") or end_payload.get("date")
        date_value = (start_payload.get("date") or (start_value or "")[:10] or (end_value or "")[:10] or None)
        busy_minutes = _calendar_busy_minutes(start_payload, end_payload)
        record_id = "calendar-%s-%s" % (slugify(calendar.get("id") or "calendar"), slugify(event_id))
        metadata = {
            "calendar_id": calendar.get("id"),
            "calendar_summary": calendar.get("summary"),
            "html_link": item.get("htmlLink"),
            "status": item.get("status"),
            "attendees_count": len(item.get("attendees") or []),
            "start": start_value,
            "end": end_value,
        }
        records.append(
            TimelineEvent(
                id=record_id,
                record_type="TimelineEvent",
                source_id=source_id,
                title=item.get("summary") or "Busy block",
                summary="Imported from Google Calendar `%s`." % (calendar.get("summary") or calendar.get("id")),
                artifact_ids=[artifact_id],
                evidence_class="contextual",
                confidence=0.94,
                date=date_value,
                start_date=(start_value or "")[:10] or date_value,
                end_date=(end_value or "")[:10] or date_value,
                tags=["calendar", "schedule-block", "calendar-%s" % slugify(calendar.get("summary") or calendar.get("id") or "unknown")],
                metadata=metadata,
                event_kind="calendar_block",
                related_record_ids=[],
            ).to_dict()
        )
        if date_value:
            grouped = grouped_by_day.setdefault(date_value, {"minutes": 0, "events": 0, "record_ids": []})
            grouped["minutes"] += busy_minutes
            grouped["events"] += 1
            grouped["record_ids"].append(record_id)
    return records, grouped_by_day


def purge_google_calendar_records(db_path: Path, start: str, end: str) -> List[str]:
    start_date = start[:10]
    end_date = end[:10]
    existing = index.list_records_by_source(db_path, GOOGLE_CALENDAR_SOURCE_ID)
    to_delete = sorted(
        record["id"]
        for record in existing
        if start_date <= (record.get("date") or record.get("start_date") or "") <= end_date
    )
    index.delete_records_by_ids(db_path, to_delete)
    return to_delete


def ensure_google_tokens(path: Path, credentials: GoogleCalendarCredentials) -> Dict[str, Any]:
    tokens = load_json_if_exists(path)
    if not tokens:
        raise GoogleCalendarError("Google token file not found at %s. Run google-calendar-exchange-code first." % path)
    expires_at = _parse_google_datetime(tokens.get("expires_at"))
    if expires_at and expires_at - timedelta(minutes=5) > datetime.now(timezone.utc):
        return tokens
    if not tokens.get("refresh_token"):
        raise GoogleCalendarError("Google tokens expired and no refresh token is available.")
    payload = _google_token_request(
        {
            "refresh_token": tokens["refresh_token"],
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "grant_type": "refresh_token",
        }
    )
    refreshed = _normalize_google_tokens(payload, refresh_token=tokens.get("refresh_token"))
    write_json(path, refreshed)
    return refreshed


def _normalize_google_tokens(payload: Dict[str, Any], refresh_token: Optional[str] = None) -> Dict[str, Any]:
    expires_in = int(payload.get("expires_in", 3600))
    expires_at = datetime.now(timezone.utc).replace(microsecond=0) + timedelta(seconds=expires_in)
    return {
        "access_token": payload["access_token"],
        "refresh_token": payload.get("refresh_token", refresh_token),
        "scope": payload.get("scope"),
        "token_type": payload.get("token_type", "Bearer"),
        "expires_at": expires_at.isoformat(),
        "raw": payload,
    }


def _google_token_request(payload: Dict[str, Any]) -> Dict[str, Any]:
    body = urlencode(payload).encode("utf-8")
    request = Request(
        GOOGLE_TOKEN_URL,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GoogleCalendarError("Google token exchange failed: %s %s" % (exc.code, detail))


def _google_request_json(
    method: str,
    url: str,
    access_token: str,
    payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    data = None
    headers = {"Authorization": "Bearer %s" % access_token, "Accept": "application/json"}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(request, timeout=30) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        raise GoogleCalendarError("Google Calendar %s failed: %s %s" % (method, exc.code, detail))


def _calendar_busy_minutes(start_payload: Dict[str, Any], end_payload: Dict[str, Any]) -> int:
    start_value = start_payload.get("dateTime")
    end_value = end_payload.get("dateTime")
    if start_value and end_value:
        start_dt = _parse_google_datetime(start_value)
        end_dt = _parse_google_datetime(end_value)
        if start_dt and end_dt:
            return max(int((end_dt - start_dt).total_seconds() // 60), 0)
    start_date = start_payload.get("date")
    end_date = end_payload.get("date")
    if start_date and end_date:
        try:
            start_dt = datetime.fromisoformat(start_date)
            end_dt = datetime.fromisoformat(end_date)
        except ValueError:
            return 24 * 60
        days = max((end_dt - start_dt).days, 1)
        return days * 24 * 60
    return 0


def _parse_google_datetime(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    if value.endswith("Z"):
        value = value[:-1] + "+00:00"
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
