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

## Tech Stack (Proposed)

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| Language | TypeScript | Accessible for AI-assisted coders, strong typing, huge ecosystem |
| Runtime | Node.js / Bun | Local execution, fast startup |
| Local storage | SQLite (via better-sqlite3 or Drizzle) | Zero-config, portable, fast |
| Schema validation | Zod | Runtime + compile-time type safety |
| Plugin system | Dynamic imports with standard interface | Simple, no framework lock-in |
| CLI | Commander.js or similar | First UI — simple, universal |
| Web dashboard | React + Vite (optional) | Later phase, not MVP |
| Testing | Vitest | Fast, TypeScript-native |
| CI | GitHub Actions | Free for open source |

> **Open question:** Should we use Python instead of / in addition to TypeScript? Many health/data science libraries are Python-first. This is a good RFC topic.

## Core Concepts

### Health Event

The fundamental unit of data. Everything is an event:

```typescript
interface HealthEvent {
  id: string;                    // UUID
  source: string;                // connector name, e.g. "apple-health"
  category: HealthCategory;      // e.g. "sleep", "activity", "nutrition", "vital"
  type: string;                  // e.g. "sleep_session", "heart_rate", "weight"
  timestamp: Date;               // when it happened
  duration?: number;             // in seconds, if applicable
  value?: number;                // numeric value if applicable
  unit?: string;                 // e.g. "bpm", "kg", "hours"
  metadata: Record<string, unknown>; // connector-specific data
  tags?: string[];               // user-defined tags
}

type HealthCategory =
  | "sleep"
  | "activity"
  | "nutrition"
  | "vital"        // heart rate, HRV, blood pressure, etc.
  | "body"         // weight, body fat, measurements
  | "mental"       // mood, stress, journal entries
  | "lab"          // blood tests, DNA, biomarkers
  | "medication"
  | "environment"  // temperature, air quality, light
  | "calendar"     // schedule, meetings, screen time
  | "custom";
```

### Connector Interface

Every connector must implement this interface:

```typescript
interface HealthConnector {
  /** Unique identifier for this connector */
  readonly id: string;

  /** Human-readable name */
  readonly name: string;

  /** What categories of data this connector provides */
  readonly categories: HealthCategory[];

  /** Description for the plugin registry */
  readonly description: string;

  /** Initialize the connector (auth, setup, etc.) */
  init(config: ConnectorConfig): Promise<void>;

  /** Fetch events within a date range */
  fetchEvents(from: Date, to: Date): Promise<HealthEvent[]>;

  /** Check if the connector is properly configured */
  validate(): Promise<{ valid: boolean; errors?: string[] }>;
}

interface ConnectorConfig {
  /** Connector-specific configuration (API keys, file paths, etc.) */
  [key: string]: unknown;
}
```

### Hypothesis

A community health experiment:

```typescript
interface Hypothesis {
  id: string;
  title: string;                  // e.g. "Caffeine cutoff at 2pm improves deep sleep"
  description: string;            // detailed explanation
  author: string;                 // GitHub username
  status: "proposed" | "active" | "completed" | "archived";

  // The experiment design
  protocol: {
    intervention: string;         // what to do differently
    duration_days: number;        // how long to run it
    metrics: string[];            // what to measure
    control_period_days?: number; // baseline measurement period
  };

  // Required data categories to participate
  required_categories: HealthCategory[];

  // Anonymized results (opt-in contributions)
  results?: AnonymizedResult[];

  created_at: Date;
  updated_at: Date;
}

interface AnonymizedResult {
  participant_hash: string;       // pseudonymized identifier
  started_at: Date;
  completed_at: Date;
  baseline_metrics: Record<string, number>;
  experiment_metrics: Record<string, number>;
  notes?: string;
}
```

## Directory Structure

```
health-os/
├── MANIFEST.md
├── ARCHITECTURE.md         # this document
├── CONTRIBUTING.md
├── CLAUDE.md               # AI development rules
├── package.json
├── tsconfig.json
│
├── core/
│   ├── schema/             # Zod schemas for HealthEvent, Hypothesis, etc.
│   ├── storage/            # SQLite storage layer
│   ├── plugin-loader/      # Dynamic connector loading
│   ├── hypothesis-engine/  # Hypothesis management and anonymization
│   └── privacy/            # Data anonymization utilities
│
├── connectors/
│   ├── _template/          # Template for new connectors
│   ├── apple-health/
│   ├── garmin/
│   ├── oura/
│   ├── google-calendar/
│   ├── manual-input/
│   └── ... (community-contributed)
│
├── ui/
│   ├── cli/                # Command-line interface
│   └── web/                # Web dashboard (future)
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

- [ ] TypeScript vs Python vs both? Multi-language connector support?
- [ ] Should the web dashboard be a separate repo or monorepo?
- [ ] How to handle real-time data (continuous glucose monitors, etc.)?
- [ ] Mobile app strategy — PWA, React Native, or just CLI + web?
- [ ] How to incentivize hypothesis participation beyond intrinsic motivation?
- [ ] Should we support a "marketplace" for connectors?
- [ ] How to handle data versioning / migration as schemas evolve?

---

*Submit an RFC to propose changes to this architecture. See `rfcs/_template.md` for the format.*
