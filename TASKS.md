# Good-first tasks (built for the agent)

Pick one and tell your agent: "let's do task N from TASKS.md". Each card says
what to do, where, how to verify, and what "done" means. Always finish with
`make check` (green) then `/ship`.

Rules for every task: pure stdlib in core; synthetic data only; reuse the C1–C5
confidence + red-flag framing from `openhealth/evidence.py`; never diagnose.

---

## Pulse (HRV)
1. **Add SDANN / SD of 5-min means** to `openhealth/modules/pulse.py`. Verify: a
   golden test on a fixed RR fixture in `tests/test_modules_pulse.py`. Done: test green.
2. **Add a "resting HR from RR" helper + metric.** Where: `pulse.py`. Verify:
   test that 1000 ms mean RR → 60 bpm. Done: metric appears in compute output.
3. **Refine LF/HF to a Welch-style average** (still stdlib). Where: `pulse.py`
   `freq_domain`. Verify: sanity test stays green + a docstring note. Done: ratio stable on the sine fixture.

## Sleep & Circadian
4. **Add sleep-efficiency** (asleep / time-in-bed) given an optional `in_bed` window.
   Where: `sleep.py`. Verify: exact golden test. Done: metric in output.
5. **Add a "consistent bedtime" score** (spread of onset clock-times). Where:
   `sleep.py`. Verify: test with two fixtures. Done: lower spread → higher score.
6. **Add a chronotype label** (early/intermediate/late) from mean midsleep, C2.
   Where: `sleep.py`. Verify: test boundaries. Done: insight framed as a question.

## Cycle
7. **Add predicted PMS window** (luteal phase note), clearly an estimate, C2.
   Where: `cycle.py`. Verify: test the dates. Done: insight with disclaimer.
8. **Add cycle-regularity score** from length spread. Where: `cycle.py`. Verify:
   regular vs irregular fixtures. Done: metric in output.

## Body
9. **Add BMI** given height (with the "BMI is a blunt tool" caveat). Where:
   `body.py`. Verify: 80 kg / 1.80 m → 24.7. Done: metric + caveat note.
10. **Add eating-window (TRE) metric** = span between first and last meal/day.
    Where: `body.py`. Verify: test. Done: metric in output.
11. **Add a longest-habit-streak record.** Where: `body.py`. Verify: test on a
    gapped list. Done: metric in output.

## New domain modules (copy an existing module as a template)
12. **Create `metabolic` module**: log glucose readings → mean, time-in-range,
    a cautious post-meal-spike prompt. Register in `modules/__init__.py`. Verify:
    new `tests/test_modules_metabolic.py`. Done: `make modules` lists it.
13. **Create `skin` module**: summarize photo observations by body zone over time
    (reuse `BodyZone`/`MediaObservation`). Verify: test. Done: registered + tested.
14. **Create `mood` sub-handling** in body or a new module: track check-in mood
    over time, surface a gentle trend. Verify: test. Done: registered + tested.

## Insight templates & safety
15. **Add an insight template** "late screen time ↔ later sleep onset" as a
    pulled hypothesis (C3, sources). Where: a new `insights/` card (see RFC-002).
    Verify: it loads and renders as a question. Done: shows a confidence chip.
16. **Add a red-flag** for resting HR persistently > 100 bpm (refer to a clinician,
    not a diagnosis). Where: `evidence.py`. Verify: unit test. Done: alert fires.
17. **Add a unit converter** (lb↔kg, °F↔°C) used by modules. Where: a new
    `openhealth/units.py`. Verify: round-trip tests. Done: used by `body.py`.

## Agent interface
18. **Add a `/today` slash command** that summarizes the latest reading per domain.
    Where: `.claude/commands/today.md` + `recent` filters. Verify: dry-run wording.
    Done: command file present and points to the skill.
19. **Improve `/log` parsing** so "weighed 79.2 today" routes to the body module
    automatically. Where: `.claude/commands/log.md` + skill notes. Done: example works.

## Connectors
20. **Add a generic CSV connector card** for a wearable export (date + metric
    columns) into the canonical schema. Where: `connectors/` + a parser. Verify:
    a synthetic CSV fixture + ingest test. Done: records land in the index.
