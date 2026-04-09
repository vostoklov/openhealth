# Contributing to OpenHealth

Welcome! This guide explains how to contribute to OpenHealth. Whether you're building a connector, proposing a hypothesis, or improving the core architecture — this document is your starting point.

## Quick Start

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-connector`
3. Make your changes following the guidelines below
4. Submit a PR using the PR template
5. Wait for review

## Ground Rules

### The Telegram + GitHub Rule

We use Telegram for discussion and vibes. We use GitHub for decisions.

**Nothing decided in Telegram is official until it's in a GitHub issue or PR.**

- Idea in Telegram chat? Great. Open a GitHub Issue to make it real.
- Architecture discussion in Telegram? Summarize it in a GitHub Discussion or RFC.
- Someone assigned a task in Telegram? Not valid until the GitHub Issue is assigned.

### Code of Conduct

- Be respectful and constructive
- Health data is sensitive — treat it with care
- Quality over speed — a working connector is worth more than three broken ones
- Help review others' PRs — it's how we all learn

## What Can I Contribute?

### 1. Build a Connector

This is the easiest way to start. Each connector integrates one health data source.

**How to claim one:**
1. Check the [Connectors project board] for unclaimed connectors
2. Open a GitHub Issue: "Connector: [Data Source Name]"
3. Describe what data it provides and which `HealthCategory` types it covers
4. Wait for approval from a maintainer (usually quick)
5. Start building using `connectors/_template/` as your starting point

**Your connector, your responsibility:**
- You own the code in your connector directory
- You can merge your own PRs (after 1 review from a core team member)
- You're responsible for tests and documentation
- If you go inactive for 30+ days, someone else may be assigned

### 2. Propose a Hypothesis

Health hypotheses are the social layer of OpenHealth. Anyone can propose one.

1. Copy `hypotheses/_template/` to a new directory
2. Fill in the hypothesis template (title, protocol, required data, etc.)
3. Submit a PR — lightweight review required
4. If accepted, the community can opt in to participate

### 3. Improve Core Architecture

Want to change how the system works? Use the RFC process.

1. Copy `rfcs/_template.md` to `rfcs/NNN-your-proposal.md`
2. Fill in the RFC: motivation, proposal, alternatives, open questions
3. Submit a PR — discussion happens on the PR
4. The BDFL makes the final call after community input

### 4. Review PRs

One of the most valuable contributions. We need reviewers. Look for PRs tagged `needs-review`.

### 5. Report Bugs & Suggest Features

Use GitHub Issues with the appropriate template.

## PR Process

### Branch naming

```
feat/connector-name     # new connector
feat/feature-name       # new feature
fix/bug-description     # bug fix
rfc/proposal-name       # RFC
docs/what-changed       # documentation
```

### Commit messages

We use [Conventional Commits](https://www.conventionalcommits.org/):

```
feat(connector): add Oura ring connector
fix(core): handle empty date ranges in storage
docs: update CONTRIBUTING.md with RFC process
refactor(schema): rename HealthRecord to HealthEvent
test(garmin): add integration tests for sleep data
```

### Review requirements

| Area | Reviews needed | Who can merge |
|------|---------------|---------------|
| `core/` | 2 reviews | BDFL only |
| `connectors/your-connector/` | 1 review from core team | Connector owner |
| `connectors/someone-elses/` | 1 review from owner + 1 from core | Core team |
| `hypotheses/` | 1 review | Any maintainer |
| `rfcs/` | Community discussion + BDFL decision | BDFL |
| `ui/` | 1 review | Any maintainer |
| Docs (*.md in root) | 1 review | Any maintainer |

### PR Checklist

Your PR should:
- [ ] Follow the connector interface (if a connector)
- [ ] Include tests (`python -m unittest discover`)
- [ ] Pass linting (`ruff check .`)
- [ ] Use type hints on all public functions
- [ ] Not contain any secrets, API keys, or tokens
- [ ] Include a clear description of what and why
- [ ] Reference the relevant GitHub Issue

## Security Rules

**These are non-negotiable:**

1. **Never commit secrets.** No API keys, tokens, passwords, or credentials in code. Use `.env` files (gitignored) and `.env.example` for templates.
2. **Never commit personal health data.** Test with synthetic data only.
3. **Pre-commit hooks will block** commits containing patterns that look like secrets.
4. **Report security issues privately** — do not open public issues for security vulnerabilities. Email the maintainer directly.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/igindin/openhealth.git
cd openhealth

# Install the package (editable)
pip install -e .

# Copy environment template
cp .env.example .env

# Run tests
python -m unittest discover

# Lint
ruff check .
```

## AI-Assisted Development

Most of us code with AI tools (Claude Code, Cursor, Copilot, etc.). This is great! But:

1. **Read `CLAUDE.md`** — it contains rules your AI tool should follow
2. **Review AI-generated code before committing** — don't blindly commit
3. **AI can't approve PRs** — human review is always required
4. **Never paste API keys into AI chat** — use environment variables

## Getting Help

- **Telegram** — quick questions, discussion, coordination
- **GitHub Discussions** — deeper topics, architecture debates
- **GitHub Issues** — bugs, feature requests, connector proposals

---

*This document is maintained by the community. To suggest changes, submit a PR.*
