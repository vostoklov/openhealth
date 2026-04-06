# Health OS

**A personal health operating system. Open-source. Local-first. Built by a community.**

`v0.1.0-alpha` | MIT License

---

## What is this?

Health OS is an open-source framework for managing your health through data, experiments, and collective knowledge.

It is **not an app**. It is an operating system — a set of connectors, schemas, and tools you compose into YOUR health system. For your body, your conditions, your hypotheses.

**The problem:** health data is scattered across dozens of services. Sleep in Oura, workouts in Garmin, bloodwork in a PDF, DNA in 23andMe, schedule in Google Calendar. Nothing connects them. No one lets you ask: *"How does my sleep correlate with my meeting load?"* or test: *"If I stop caffeine after 2pm, does my deep sleep improve?"*

Health OS solves this.

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│                  Your Machine                    │
│                                                  │
│  ┌──────────┐  ┌──────────┐  ┌──────────────┐   │
│  │  Apple   │  │  Garmin  │  │   Manual     │   │
│  │  Health  │  │ Connect  │  │   Input      │   │
│  └────┬─────┘  └────┬─────┘  └──────┬───────┘   │
│       │              │               │           │
│       ▼              ▼               ▼           │
│  ┌──────────────────────────────────────────┐    │
│  │        Unified Health Schema             │    │
│  │   (events, metrics, observations)        │    │
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

### Three layers

| Layer | What it does | Who maintains it |
|-------|-------------|-----------------|
| **Core** (`core/`) | Data schema, storage, plugin loader, privacy, hypothesis engine | Project maintainer |
| **Connectors** (`connectors/`) | Integrations with data sources (Oura, Garmin, Apple Health, DNA, calendar...) | Each contributor owns their connector |
| **Hypotheses** (`hypotheses/`) | Community health experiments with anonymized data | Anyone can propose |

---

## Principles

1. **Your data stays with you.** Everything is stored locally. No cloud accounts, no tracking, no ads. Data only leaves your machine if you explicitly choose to share it.

2. **Modular by design.** Each connector is a plugin. Install only what you need.

3. **Hypotheses as a social layer.** The unique power of Health OS is the hypothesis engine — a shared space where people propose health experiments, define protocols, and optionally contribute anonymized results. The more people participate, the more we all learn.

4. **Quality over speed.** 5 working connectors beat 50 broken ones. Security and privacy are non-negotiable.

5. **Diversity of health domains.** Chronic conditions, athletic performance, aging biomarkers, injury recovery — the architecture supports all of it.

6. **AI-native development.** Built by people using AI coding tools (Claude Code, Cursor, Copilot) with strong guardrails, clear interfaces, and automated quality checks.

---

## Project structure

```
health-os/
├── MANIFEST.md             # Vision and values
├── ARCHITECTURE.md         # Technical architecture (RFC-001)
├── CONTRIBUTING.md         # Contribution rules
├── CLAUDE.md               # Rules for AI coding tools
│
├── core/                   # Protected core (Python)
│   ├── schema/             # Dataclasses, JSON Schema
│   ├── storage/            # SQLite local storage
│   ├── plugin_loader/      # Dynamic connector loading
│   ├── hypothesis_engine/  # Experiment management
│   └── privacy/            # Data anonymization
│
├── connectors/             # One per data source
│   └── _template/          # Starter template for new connectors
│
├── hypotheses/             # Community experiments
│   ├── _template/          # Hypothesis proposal template
│   └── caffeine-cutoff-sleep/  # Example hypothesis
│
├── ui/
│   ├── cli/                # Command-line interface (Python)
│   └── web/                # Web dashboard (Next.js, future)
│
└── rfcs/                   # Architecture proposals
```

---

## How to contribute

### Quick start

```bash
git clone https://github.com/health-os/health-os.git
cd health-os
pip install -e .
python -m unittest discover
```

### What you can do

| Action | How to start | Difficulty |
|--------|-------------|-----------|
| **Build a connector** | Copy `connectors/_template/`, implement `HealthConnector` interface | Medium |
| **Propose a hypothesis** | Copy `hypotheses/_template/`, fill in the template, submit a PR | Easy |
| **Improve architecture** | Write an RFC in `rfcs/`, discuss on the PR | Advanced |
| **Review PRs** | Look for `needs-review` label | Any |
| **Report bugs** | Open an Issue using the template | Easy |

### Rules

- **Telegram** = discussion. **GitHub** = decisions and code.
- Nothing from chat is official until there's an Issue or PR.
- All changes via Pull Request. Direct push to `main` is blocked.
- Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`
- Details: [CONTRIBUTING.md](./CONTRIBUTING.md)

---

## The Hypothesis Engine

This is what makes Health OS more than a tracker — it's a **collective knowledge platform**.

### How it works

1. Someone proposes a hypothesis: *"Stopping caffeine after 2pm improves deep sleep by 15+ minutes"*
2. A protocol is defined: 14-day baseline + 14-day experiment
3. Participants connect their data sources and follow the protocol
4. After completion, they contribute **anonymized** averages
5. The community sees aggregated results

### The flywheel

More connectors → more data sources → more hypotheses can be tested → more value for everyone.

---

## Security

**Non-negotiable:**

- No API keys, tokens, or passwords in code. Only `.env` (gitignored)
- No real health data in the repository. Synthetic test data only
- Pre-commit hooks block commits containing secrets
- CI scans every PR for leaks
- Hypothesis data is anonymized before sharing

---

## Tech stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.10+ (core, connectors) / TypeScript (UI, future) |
| Runtime | Python / Node.js (UI) |
| Storage | SQLite (local, stdlib sqlite3) |
| Validation | JSON Schema + dataclasses |
| Testing | unittest |
| CI | GitHub Actions |

---

## Governance

**BDFL + RFC model:**

- One maintainer makes final calls on architecture and merges
- All decisions published as RFCs (Request for Comments)
- Anyone can submit an RFC to change any part of the system
- Discussion happens publicly on GitHub
- Principle: *"Strong opinions, loosely held"*

Governance will evolve as the project matures. Trusted contributors earn expanded rights.

---

## What's open for change (everything)

This is `v0.1.0-alpha`. **Everything is up for discussion:**

- [x] ~~TypeScript vs Python vs multi-language support?~~ **Decided:** Python for core + connectors, TypeScript/Next.js for UI
- [ ] Web dashboard — separate repo or monorepo?
- [ ] Real-time data (CGM, pulse oximeters)?
- [ ] Mobile app — PWA, React Native, or CLI + web only?
- [ ] How to incentivize hypothesis participation?
- [ ] Connector "marketplace"?
- [ ] Data versioning and schema migration strategy?

To propose a change: copy `rfcs/_template.md`, fill it in, submit a PR.

---

## License

[MIT](./LICENSE) — do what you want, just keep the copyright notice.

---

*Health OS is built by a community. Join us.*
