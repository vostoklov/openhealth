# RFC-002: Community contribution model — code, norms, and insight templates

**Status:** draft
**Author:** igindin
**Date:** 2026-05-29

## Motivation

OpenHealth's goal is to let people pool not just code but *knowledge* — what
patterns to look for, what a marker means, how a protocol played out — without
anyone uploading their private health history. The hard problem is doing this
while keeping the project's first principle intact: **personal health data never
leaves the user's machine.**

A survey of the field shows two failure modes to avoid:
- Projects that keep everything local (Fasten, open-health) get strong privacy
  but no shared learning layer.
- Projects that pool raw user contributions risk leaking sensitive data.

The best contribution communities (Habitica, Open Food Facts, wger) succeed by
**separating personal data from shareable, anonymized artifacts** and moderating
the shared layer.

## Proposal

Split contributions into three streams. Only the first two ever enter the repo
or any shared pool. The third never leaves the user's machine.

### Stream 1 — Code (connectors, parsers, core)

Standard open-source flow: PR with tests, no secrets, no real data. A new data
source is a new plugin under `connectors/`, following the source-exporter
pattern (each source produces canonical records; the core is untouched). Source
metadata lives in declarative files so adding a source rarely touches engine
code.

### Stream 2 — Knowledge artifacts (the new part)

Two anonymized, reviewable artifact types that carry knowledge without personal
data:

**(a) Reference norms** — machine-readable reference ranges, LOINC mappings, unit
conversions, contributed to the shared *external reference layer* (distinct from
personal evidence). Example: adding a marker to `reference_ranges.py` with its
source. These are facts about tests, not about any person.

**(b) Insight templates** — a reusable hypothesis pattern with no one's data
attached. Shape:

```
id: late-caffeine-deep-sleep
statement: "Caffeine after ~2pm may reduce deep sleep."
requires: [caffeine_intake_time, deep_sleep_minutes]
confidence: C3          # see docs/methodology/evidence-and-trust.md
sources: [<pubmed/url>, ...]
validation: "n-of-1, ABAB, 2-week baseline, caffeine cutoff toggled weekly"
```

A user can *pull* a template and run it against their own local data; the
template itself contains only the idea, the required signals, a confidence
label, sources, and a suggested validation protocol. Results stay local unless
the user explicitly opts into an aggregated, anonymized study (future work,
gated by `core/privacy/`).

### Stream 3 — Personal data (never shared)

Raw files, observations, photos, lab values. Local-first, immutable once
archived. Telegram and other channels are transport, not storage (bots have no
end-to-end encryption). This stream has no PR path by design.

### Trust and moderation

- Every Stream-2 artifact carries a **confidence label (C1–C5)** and **sources**.
  Unsourced insight templates default to C1 and are shown as speculation.
- **Tiered review** (Habitica-style): new contributors' knowledge artifacts need
  maintainer review; trusted contributors earn merge rights over time.
- Reference norms must cite an authoritative source (LOINC, a guideline, a
  peer-reviewed range). No "I heard that…".
- Insight templates that imply diagnosis or treatment are rejected; templates
  phrase findings as questions per the methodology doc.

## Alternatives Considered

### Alternative A: Pool anonymized raw results centrally from day one
- Description: participants upload de-identified metric averages to a shared DB.
- Rejected for v1: requires a robust anonymization + hosting + consent stack
  (`core/privacy/`) that does not exist yet, and raises re-identification risk.
  Deferred until the privacy layer is built and audited.

### Alternative B: Adopt FHIR/openEHR as the internal model and share via it
- Description: use a clinical standard as the canonical model and exchange format.
- Rejected as the *internal* model: too heavy for beginners and lifestyle data.
  Instead, keep a light internal model and use Open mHealth (lifestyle) and FHIR
  (clinical) as optional import/export adapters at the edges.

## Impact

- **Breaking changes:** no. Adds artifact types and contribution paths.
- **Affected areas:** `connectors/`, a new `insights/` (templates) directory,
  `reference_ranges.py`, `docs/methodology/`, CONTRIBUTING.md, `core/privacy/`
  (future, for opt-in aggregation).
- **Migration effort:** low. Existing records and parsers are unaffected.

## Open Questions

- [ ] Directory and schema for insight templates (`insights/` + JSON Schema)?
- [ ] Minimum source bar for a reference-norm contribution?
- [ ] When (if ever) to build the opt-in anonymized aggregation in `core/privacy/`?
- [ ] How to version insight templates as evidence evolves?

---

*To submit changes to this RFC, open a PR. Discussion happens on the PR.*
