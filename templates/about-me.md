# About Me — your OpenHealth context

**Fill this in first. It is the single most useful thing you can do.**

OpenHealth has no GUI — you talk to an AI agent, and the agent runs the local
tools for you. But an agent starts every session with a blank memory. This file
is the context it reads first: who you are, what you actually care about, and
where your data lives. Without it, the agent re-asks the same questions every
time and gives generic answers. With it, the very first reply is grounded in
*your* body and *your* goal.

## How to use it

1. Copy this file to your **private** location (outside this public repo — e.g.
   your local overlay or a gitignored folder). **Never commit your real
   answers** — this is personal health context.
2. Fill in what you know. Blanks are fine; you can grow it over time.
3. Point your agent at it at the start of a session ("read my about-me, then …").
4. When something durable changes (a new goal, a new data source), update it
   here rather than re-explaining in chat. The file is the memory; the chat is not.

---

## Who I am

- **Name / what to call me:**
- **Age / sex (if relevant to interpretation):**
- **Rough baseline:** (general fitness, sleep tendencies, anything notable)
- **Known conditions / things a helper should keep in mind:** (optional)
- **Medications / supplements I take regularly:** (optional — context, not advice)

> The agent never diagnoses or prescribes. This is background so its prompts are
> relevant, not a medical record.

## My health goal

- **The one thing I most want to understand or improve right now:**
  _(e.g. "what actually moves my HRV (rMSSD)", "sleep more consistently",
  "understand what tanks my recovery")_
- **Why it matters to me:**
- **How I'd know it worked (a signal I can watch):**
- **A hypothesis I'd like to test (if any):**
  _(e.g. "cutting caffeine after 2pm improves my deep sleep")_

> A personal pattern stays a weak signal until a repeated on/off (n-of-1) test
> survives. Goals here become experiments, not conclusions.

## Where my data lives

Tick what you have; the agent meets you where you are.

- [ ] **Apple Health** export (`export.xml` / `.zip`) — path or "on my iPhone"
- [ ] **WHOOP** (connected via API / OAuth)
- [ ] **Google Calendar** (for meeting-load / life-context signals)
- [ ] **Bloodwork / lab PDFs** — where they are
- [ ] **A wearable not yet connected** (Oura, Garmin, …) — which one
- [ ] **Mostly manual** — I'll log check-ins by talking to the agent
- **Anything else worth knowing:**

## Tracking style

- **How much friction I'll tolerate:** _(daily check-in / weekly / passive only)_
- **Behaviors I care most about tracking:** _(e.g. alcohol, late caffeine,
  late meals, stress, training)_
- **Reminders I want — or don't:**

---

*Keep this honest and short. The agent reads it, not a form. Update it whenever
the real picture changes.*
