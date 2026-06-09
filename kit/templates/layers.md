# Data layers (the model behind OpenHealth)

Your health data isn't one pile — it's layers. Keeping them separate is what
turns a chat into a system and keeps the agent honest.

## The layers
1. **Sources (raw, immutable)** — the original exports/PDFs/notes exactly as they
   came. Never edited. Everything else is derived from these.
2. **Facts** — objective records lifted from a source: a lab value, a date, a
   diagnosis on paper. High confidence, source-linked.
3. **Observations** — measured signals over time: steps, HRV, weight, sleep
   duration. One per day per metric (what the Apple Health import produces).
4. **Interventions** — things you did: a supplement, a fast, a new routine, a
   med. With start/end windows so effects can be lined up.
5. **Context notes** — subjective: mood, energy, "felt foggy Wednesday",
   travel, stress. The glue for patterns.
6. **Insights (hypotheses)** — what the system *suggests*, never concludes.
   Always carries a confidence label (C1–C5); C3 and below are questions.

## Why it matters
- The agent can say *"this is a fact"* vs *"this is a weak guess"* — no
  hallucinated certainty.
- Personal patterns stay **C2 (weak signal)** until an on/off switch repeats
  (that's what `/protocol` is for).
- A red flag (critical value, crisis language) is its own thing — it stops
  interpretation and points you to a clinician.

## In OpenHealth
These map to the records in `openhealth/models.py` (Observation, Intervention,
ContextNote, InsightHypothesis, PatternAlert) and the C1–C5 grading in
`openhealth/evidence.py`.
