# Core Schema

Dataclasses and JSON Schema definitions for the OpenHealth data model.

## Key Types

- `RecordBase` — base class for all health records
- `Observation` — a single measurement (heart rate, weight, mood)
- `TimelineEvent` — a health event with duration (sleep session, workout)
- `Intervention` — a deliberate action (medication, supplement)
- `HealthCategory` — categories of health data (sleep, activity, vital, etc.)
- `HealthConnector` — the Protocol every connector must implement
- `Hypothesis` — community health experiment definition
- `AnonymizedResult` — anonymized experiment result

## Status

The canonical models live in `openhealth/models.py`. JSON Schemas live in `schemas/`.
