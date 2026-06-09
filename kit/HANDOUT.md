# Health Sprint Kit — start here

A small library of skills you drive through **Claude Code / Codex**. You talk; it
logs your data, finds patterns, and helps you build your own health system. No
GUI to learn. Your data stays on your machine.

> **You do not need 20 years of scans or a WHOOP.** Start with an iPhone and one
> question. Match nobody. The people loading decades of PDFs are optional
> inspiration, not the bar.

## 15-minute start

1. Open this folder in Claude Code (or Codex). Say: **"run make setup"**.
2. Say: **`/kit`** and what you want, e.g. *"sleep + a daily check-in"*. It
   installs only what you asked for.
3. Get one source of data in:
   - iPhone → Health app → your photo (top right) → **Export All Health Data** →
     you get a `.zip`. Then say: *"import my Apple Health export from ~/Downloads"*.
   - Or just one lab PDF, or even nothing — say *"start with what I have"*.
4. Pick **one** question: *"what moves my energy?"* / *"what breaks my sleep?"* /
   *"how does coffee affect me?"*. Say it; the agent sets up a tiny experiment.
5. Say **`/checkin`** once a day during the live test. That's it.

## What's inside (see `kit/registry.yaml`)
- **Signals** (get data in): Apple Health, WHOOP, CSV, lab PDF (Oura/genetics scaffolded).
- **Knowledge**: labs, sleep, cycle, body, metabolic, skin (pulse/HRV optional).
- **Actions**: `/track` your own habits, `/checkin`, `/protocol` (n-of-1).
- **Trust**: deep-research + a hypothesis/critic/safety consilium, evidence C1–C5.
- **System**: `/kit` loader, an optional adaptive daily cockpit.

## The rules
- This is a **thinking partner, not a doctor.** No diagnoses. Medical decisions
  go to a clinician. Anything alarming → stop and seek care.
- Every meaningful number carries a **confidence label (C1–C5)**; low confidence
  is phrased as a question.
- **Don't copy any skill blindly.** A repo may be over-engineered for you, or
  built for a different health goal. Adapt it to yours.
- Local-first: nothing is uploaded. Real data and secrets stay on your machine.

OpenHealth is early and rough in places — that's fine. You're building *yours*.
