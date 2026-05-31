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

## Next
1. Sleep & Circadian module (port/extend circadian logic; midsleep, social
   jetlag, rough phase — all C2-C3 with limits disclosed).
2. Cycle, Body (weight/fasting), Metabolic, Skin modules.
3. Agent-native interface: CLI subcommands + Claude Code slash commands +
   health-agent orchestrator skill.
4. Newcomer onboarding: make setup, pre-commit, CI, hidden-git scripts, ≥20
   agent task cards, beginner AGENTS/CLAUDE/CONTRIBUTING.
5. core/privacy, headless API + TS SDK + OpenAPI, A2UI adapter (verify package).

## Notes
- Core stays stdlib-only (no numpy) per ARCHITECTURE rule.
- `circadian.py` exists in the private health_os overlay, not in public repo —
  reimplement original here.
- Every module reuses C1–C5 + red flags; nothing diagnoses.
