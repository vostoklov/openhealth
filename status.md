# Status — agent-native build

Branch: `feat/agent-native-os` (not pushed). Tests: 21 passing.

## Done
- Module plugin system: `openhealth/modules/{__init__,base}.py` — `HealthModule`
  contract, registry, `load_builtin()`, `KNOWN_DOMAINS`.
- **Pulse** module (`openhealth/modules/pulse.py`): stdlib HRV — SDNN, RMSSD,
  pNN50, mean HR (golden-tested exact), LF/HF best-effort via interpolated
  tachogram + naive DFT (sanity-tested). Readiness insight capped to C2 and
  framed as a question per `evidence`.
- Tests: `tests/test_modules_pulse.py` (8 cases). Full suite 21/21 green.
- Planning: plan.md, status.md, SOURCES.md.

## Done (cont.)
- All 6 domain modules: pulse, sleep, cycle, body, metabolic, skin — each with
  schema()+compute()+tests, evidence-graded, no diagnosis. `make modules` lists all.
- Agent-native interface: CLI `modules`/`module`/`recent`; health-agent skill;
  /pulse /sleep /cycle /body /checkin /log /insights /trends /protocol /ship.
- Onboarding (no-git): Makefile (`make setup`/`check`), .pre-commit-config
  (secret-scan/large-file/lint), scripts/oh_ship.py + /ship, docs/contributing/
  start-here.md, TASKS.md (20 agent cards). CONTRIBUTING points to the no-git path.
- core/privacy: strip_pii, pseudonymize, anonymize_for_share, is_anonymized + tests.
- 43 tests passing.

## Next
1. Headless API + typed TS SDK + OpenAPI (consumes canonical records/insights).
2. A2UI adapter: Insight -> declarative UI intent + catalog schema + golden
   tests, no render (confirm google/A2UI vs codaaiteam/ai2ui first).
3. Connectors: Apple Health export, Google Fit, generic CSV (good-first cards exist).
4. Wire module insights into contexts so /insights surfaces them in briefs.

## Notes
- Core stays stdlib-only (no numpy) per ARCHITECTURE rule.
- `circadian.py` exists in the private health_os overlay, not in public repo —
  reimplement original here.
- Every module reuses C1–C5 + red flags; nothing diagnoses.
