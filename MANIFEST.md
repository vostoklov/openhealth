# OpenHealth Manifest

**Version:** 0.1 (RFC-001 — open for community revision)

## What is OpenHealth?

OpenHealth is an open-source, local-first personal health operating system built by a community of people who care about their health and want to understand it better through data, experiments, and shared knowledge.

It is NOT another health app. It is a **framework** — a set of connectors, schemas, and tools that let you build YOUR health system, tailored to YOUR body, YOUR conditions, and YOUR hypotheses.

## Why this exists

Modern health tracking is fragmented:
- Your sleep is in Oura, your workouts in Garmin, your bloodwork in a PDF, your DNA in 23andMe, your calendar in Google
- No single tool connects them
- No one lets you ask: "Does my sleep quality correlate with my meeting load?"
- No one lets you test: "If I stop caffeine after 2pm for 30 days, does my HRV improve?"

OpenHealth connects everything into one local-first system where YOU own your data and YOU run your experiments.

## Core Principles

### 1. Local-first, privacy-by-default
Your health data never leaves your machine unless you explicitly choose to share it. No cloud accounts required. No tracking. No ads. No data sales.

### 2. Modular and connectable
OpenHealth is built as a set of plugins (connectors). Each connector handles one data source. You compose your own setup. No one needs every connector — you install what matters to you.

### 3. Community-driven hypotheses
The unique power of OpenHealth is the **hypothesis engine** — a shared space where people propose health experiments, define protocols, and (optionally) contribute anonymized results back to the community. The more people participate, the more we all learn.

### 4. Built in public, quality over speed
All code is open source. All architecture decisions go through RFCs. Quality matters — we'd rather have 5 solid connectors than 50 broken ones. Security and privacy are non-negotiable.

### 5. Diversity of health domains
Everyone's health journey is different. Some people track chronic conditions, some optimize athletic performance, some monitor aging biomarkers, some manage injuries. OpenHealth is designed to accommodate all of these through its plugin architecture.

### 6. AI-native development
This project is built by people using AI coding tools (Claude Code, Cursor, Copilot, etc.). Our development process is designed for this reality — with strong guardrails, clear interfaces, and automated quality checks.

## The Network Effect

OpenHealth becomes more valuable as the community grows:
- More **connectors** = more data sources you can integrate
- More **hypotheses** = more experiments you can join or learn from
- More **anonymized data** = stronger evidence for what works
- More **contributors** = better code, more features, more reliability

This is the flywheel. Each contribution makes the system better for everyone.

## Governance

This project uses a **BDFL + RFC** model:
- One maintainer (project founder) holds final decision authority on architecture and merges
- All architectural decisions are published as RFCs (Request for Comments)
- Anyone can submit an RFC to change any part of the system
- Discussion happens publicly on GitHub
- The BDFL commits to "strong opinions, loosely held" — the structure exists to enable work, not to restrict creativity

As the project matures, governance will evolve. Trusted contributors will earn maintainer rights through consistent, quality contributions.

## Who is this for?

- People who want to understand their health through data
- People who are curious about health experiments and self-quantification
- Developers and AI-assisted coders who want to build health tools
- Health enthusiasts who want to contribute to community knowledge
- Anyone frustrated with fragmented health data silos

## How to participate

See [CONTRIBUTING.md](./CONTRIBUTING.md) for detailed contribution guidelines.

The simplest ways to start:
1. **Claim a connector** — pick a health data source and build the integration
2. **Propose a hypothesis** — submit a health experiment idea for the community
3. **Improve the architecture** — submit an RFC with your ideas
4. **Review PRs** — help maintain quality by reviewing others' code
5. **Test and report bugs** — use the system and tell us what breaks

---

*This manifest is a living document. To propose changes, submit a PR modifying this file with your reasoning.*
