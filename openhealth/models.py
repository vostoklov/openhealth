from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class BodyZone(str, Enum):
    FACE = "face"
    EYES = "eyes"
    EYELIDS = "eyelids"
    SCALP = "scalp"
    NECK = "neck"
    CHEST = "chest"
    ARMS = "arms"
    HANDS = "hands"
    TORSO = "torso"
    LEGS = "legs"
    FEET = "feet"
    CUSTOM = "custom"


class VisibleAttribute(str, Enum):
    REDNESS = "redness"
    PUFFINESS = "puffiness"
    DRYNESS = "dryness"
    IRRITATION = "irritation"
    SWELLING = "swelling"
    BREAKOUT_INTENSITY = "breakout_intensity"
    DISCOLORATION = "discoloration"
    TEXTURE_CHANGE = "texture_change"


def dataclass_dict(instance: Any) -> Dict[str, Any]:
    return asdict(instance)


@dataclass
class SourceManifest:
    source_id: str
    source_type: str
    owner: str
    label: str
    created_at: str
    coverage_start: Optional[str]
    coverage_end: Optional[str]
    files: List[str]
    parser_status: str
    notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_dict(self)


@dataclass
class ArtifactManifest:
    artifact_id: str
    source_id: str
    source_type: str
    original_path: str
    archived_path: str
    checksum: str
    mime_type: str
    size_bytes: int
    provenance: Dict[str, Any]
    privacy: Dict[str, Any]
    parser_notes: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_dict(self)


@dataclass
class RecordBase:
    id: str
    record_type: str
    source_id: str
    title: str
    summary: str
    artifact_ids: List[str]
    evidence_class: str
    confidence: float
    captured_at: Optional[str] = None
    date: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    location: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_dict(self)


@dataclass
class TimelineEvent(RecordBase):
    event_kind: str = "event"
    related_record_ids: List[str] = field(default_factory=list)


@dataclass
class Observation(RecordBase):
    observation_kind: str = "signal"
    metric_name: Optional[str] = None
    value: Optional[Any] = None
    unit: Optional[str] = None


@dataclass
class Intervention(RecordBase):
    intervention_kind: str = "routine"
    subject: Optional[str] = None
    status: str = "active"
    dosage: Optional[str] = None
    cadence: Optional[str] = None


@dataclass
class ContextNote(RecordBase):
    note_kind: str = "note"
    people: List[str] = field(default_factory=list)
    themes: List[str] = field(default_factory=list)
    mood: Optional[str] = None


@dataclass
class ReferenceCase(RecordBase):
    origin: Optional[str] = None
    applicability: Optional[str] = None
    external_links: List[str] = field(default_factory=list)


@dataclass
class InsightHypothesis(RecordBase):
    statement: str = ""
    evidence_record_ids: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)


@dataclass
class MediaObservation(RecordBase):
    body_zone: str = "custom"
    side: Optional[str] = None
    visible_attributes: List[str] = field(default_factory=list)
    severity: Optional[str] = None
    comparison_target_id: Optional[str] = None
    media_path: Optional[str] = None
    observation_kind: str = "media_observation"


@dataclass
class PatternAlert(RecordBase):
    relationship: str = ""
    related_signals: List[str] = field(default_factory=list)
    evidence_count: int = 0
    missing_data: Optional[str] = None
    suggested_validation: Optional[str] = None
    evidence_record_ids: List[str] = field(default_factory=list)


@dataclass
class ValidationPrompt(RecordBase):
    prompt_text: str = ""
    validation_type: str = "observation"
    duration_days: int = 5
    target_zone: Optional[str] = None
    hypothesis_id: Optional[str] = None
    status: str = "pending"


@dataclass
class IntakeEnvelope:
    submission_id: str
    submitted_at: str
    channel: str
    author: str
    text: Optional[str] = None
    location: Optional[str] = None
    attachments: List[Dict[str, Any]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return dataclass_dict(self)
