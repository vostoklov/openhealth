# Architecture (RFC-001)

**Status:** Draft — open for community review
**Author:** Project Founder
**Date:** 2026-04-05

> This is the initial architectural proposal. To suggest changes, submit a PR or open a GitHub Discussion.

## Overview

Health OS is a **local-first, plugin-based** system. Data lives on the user's machine. Connectors pull data from external sources into a unified schema. The hypothesis engine allows community experiments on anonymized, opt-in data.

```
┌──────────────────────────────────────────────────┐
│                    User's Machine                │
│                                                  │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐ │
│  │ Apple      │  │ Garmin     │  │ Manual     │ │
│  │ Health     │  │ Connect    │  │ Input      │ │
│  │ Connector  │  │ Connector  │  │ Connector  │ │
│  └─────┬──────┘  └─────┬──────┘  └─────┬──────┘ │
│        │               │               │        │
│        ▼               ▼               ▼        │
│  ┌──────────────────────────────────────────┐    │
│  │          Unified Health Schema           │    │
│  │    (events, metrics, observations)       │    │
│  └──────────────┬───────────────────────────┘    │
│                 │                                │
│        ┌────────┴────────┐                       │
│        ▼                 ▼                       │
│  ┌──────────┐    ┌──────────────┐                │
│  │ Personal │    │  Hypothesis  │                │
│  │ Dashboard│    │  Engine      │                │
│  └──────────┘    └──────┬───────┘                │
│                         │                        │
└─────────────────────────┼────────────────────────┘
                          │ (opt-in, anonymized)
                          ▼
                 ┌──────────────────┐
                 │  Community       │
                 │  Hypothesis Pool │
                 └──────────────────┘
```

## Tech Stack

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | Python 3.10+ (core, connectors) / TypeScript (UI, future) | Python for health/data science ecosystem; TypeScript for web UI |
| Runtime | Python / Node.js (UI) | Local execution, fast startup |
| Local storage | SQLite (via sqlite3 stdlib) | Zero-config, portable, fast |
| Schema validation | JSON Schema + dataclasses | Runtime validation + type safety |
| Plugin system | Dynamic imports with Protocol class | Simple, no framework lock-in |
| CLI | argparse | First UI — simple, stdlib, universal |
| Web dashboard | Next.js (future, separate) | Later phase, not MVP |
| Testing | unittest | Stdlib, no extra dependencies |
| CI | GitHub Actions | Free for open source |

## Core Concepts

### Core Data Models

The fundamental data models. Built with Python dataclasses:

```python
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal


class HealthCategory(str, Enum):
    SLEEP = "sleep"
    ACTIVITY = "activity"
    NUTRITION = "nutrition"
    VITAL = "vital"            # heart rate, HRV, blood pressure, etc.
    BODY = "body"              # weight, body fat, measurements
    MENTAL = "mental"          # mood, stress, journal entries
    LAB = "lab"                # blood tests, DNA, biomarkers
    MEDICATION = "medication"
    ENVIRONMENT = "environment"  # temperature, air quality, light
    CALENDAR = "calendar"      # schedule, meetings, screen time
    CUSTOM = "custom"


@dataclass
class RecordBase:
    """Base class for all health records."""
    id: str                          # UUID
    source: str                      # connector name, e.g. "apple-health"
    timestamp: datetime              # when it happened
    metadata: dict[str, object] = field(default_factory=dict)
    tags: list[str] = field(default_factory=list)


@dataclass
class Observation(RecordBase):
    """A single health observation (heart rate, weight, mood, etc.)."""
    category: HealthCategory = HealthCategory.CUSTOM
    type: str = ""                   # e.g. "heart_rate", "weight"
    value: float | None = None
    unit: str | None = None          # e.g. "bpm", "kg"


@dataclass
class TimelineEvent(RecordBase):
    """A health event with duration (sleep session, workout, etc.)."""
    category: HealthCategory = HealthCategory.CUSTOM
    type: str = ""                   # e.g. "sleep_session", "run"
    duration_seconds: float | None = None
    value: float | None = None
    unit: str | None = None


@dataclass
class Intervention(RecordBase):
    """A deliberate action taken (medication, supplement, protocol change)."""
    name: str = ""
    dosage: str | None = None
    frequency: str | None = None
    notes: str | None = None
```

### Connector Interface

Every connector must implement this Protocol:

```python
from typing import Protocol, Sequence
from datetime import datetime


class HealthConnector(Protocol):
    """Protocol that all connectors must implement."""

    @property
    def id(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def categories(self) -> Sequence[str]: ...

    @property
    def description(self) -> str: ...

    async def init(self, config: dict) -> None: ...

    async def fetch_events(self, from_date: datetime, to_date: datetime) -> list[dict]: ...

    async def validate(self) -> tuple[bool, list[str] | None]: ...
```

### Hypothesis

A community health experiment:

```python
@dataclass
class HypothesisProtocol:
    """The experiment design."""
    intervention: str              # what to do differently
    duration_days: int             # how long to run it
    metrics: list[str]             # what to measure
    control_period_days: int | None = None  # baseline measurement period


@dataclass
class AnonymizedResult:
    """Anonymized result from a hypothesis participant."""
    participant_hash: str          # pseudonymized identifier
    started_at: datetime
    completed_at: datetime
    baseline_metrics: dict[str, float]
    experiment_metrics: dict[str, float]
    notes: str | None = None


@dataclass
class Hypothesis:
    id: str
    title: str                     # e.g. "Caffeine cutoff at 2pm improves deep sleep"
    description: str               # detailed explanation
    author: str                    # GitHub username
    status: Literal["proposed", "active", "completed", "archived"]
    protocol: HypothesisProtocol
    required_categories: list[HealthCategory]
    created_at: datetime
    updated_at: datetime
    results: list[AnonymizedResult] = field(default_factory=list)
```

## Directory Structure

```
health-os/
├── MANIFEST.md
├── ARCHITECTURE.md         # this document
├── CONTRIBUTING.md
├── CLAUDE.md               # AI development rules
├── pyproject.toml
├── requirements.txt
│
├── core/
│   ├── __init__.py
│   ├── schema/             # Dataclasses, JSON Schema definitions
│   ├── storage/            # SQLite storage layer (stdlib sqlite3)
│   ├── plugin_loader/      # Dynamic connector loading
│   ├── hypothesis_engine/  # Hypothesis management and anonymization
│   └── privacy/            # Data anonymization utilities
│
├── connectors/
│   ├── _template/          # Template for new connectors
│   ├── apple_health/
│   ├── garmin/
│   ├── oura/
│   ├── google_calendar/
│   ├── manual_input/
│   └── ... (community-contributed)
│
├── ui/
│   ├── cli/                # Command-line interface (Python, argparse)
│   └── web/                # Web dashboard (Next.js, future, separate)
│
├── hypotheses/
│   ├── _template/          # Template for proposing hypotheses
│   └── ... (community-proposed)
│
├── rfcs/
│   ├── 001-initial-architecture.md  # this document
│   └── _template.md
│
└── .github/
    ├── CODEOWNERS
    ├── PULL_REQUEST_TEMPLATE.md
    ├── ISSUE_TEMPLATE/
    └── workflows/
        ├── ci.yml          # Tests, linting, type-checking
        ├── security.yml    # Secret scanning, dependency audit
        └── connector-test.yml  # Per-connector integration tests
```

## Security & Privacy Requirements

1. **No secrets in code** — all API keys, tokens, etc. go in `.env` (gitignored). CI blocks commits containing secrets.
2. **No cloud dependency** — the system must work fully offline. Cloud features are always opt-in.
3. **Data anonymization** — any data shared with the community hypothesis pool must be stripped of PII and use pseudonymized identifiers.
4. **No telemetry** — Health OS does not phone home. Ever.
5. **Encryption at rest** — local SQLite database should support optional encryption (SQLCipher or similar).

## Open Questions (for community RFCs)

- [x] ~~TypeScript vs Python vs both?~~ **Decided:** Python for core + connectors, TypeScript/Next.js for UI (future)
- [ ] Should the web dashboard be a separate repo or monorepo?
- [ ] How to handle real-time data (continuous glucose monitors, etc.)?
- [ ] Mobile app strategy — PWA, React Native, or just CLI + web?
- [ ] How to incentivize hypothesis participation beyond intrinsic motivation?
- [ ] Should we support a "marketplace" for connectors?
- [ ] How to handle data versioning / migration as schemas evolve?

---

*Submit an RFC to propose changes to this architecture. See `rfcs/_template.md` for the format.*
