# OpenHealth — AI Development Rules

This file is read by AI coding tools (Claude Code, Cursor, Copilot, etc.) to ensure consistent code quality across all contributors.

## Project Overview

OpenHealth is a local-first, plugin-based personal health operating system. Data stays on the user's machine. Connectors pull data from external sources into a unified schema.

## Language & Standards

- **Language:** Python 3.10+ with type hints (core, connectors) / TypeScript (UI, future)
- **Runtime:** Python (core) / Node.js (UI, future)
- **Testing:** unittest
- **Linting:** ruff
- **Package manager:** pip / pyproject.toml

> **Note:** UI components (future) will use TypeScript/Next.js. These rules cover the Python core and connectors.

## Code Rules

### Python
- Use type hints everywhere — function signatures, variables, return types
- Never use `Any` — use `object`, `Unknown`, or define proper types
- Use `dataclasses` for data models
- Use JSON Schema for runtime validation at system boundaries
- Use `Protocol` classes for public contracts (interfaces)
- Follow PEP 8 naming conventions (snake_case for functions/variables, PascalCase for classes)

### Connectors
- Every connector MUST implement the `HealthConnector` protocol from `core/schema`
- Connector code lives in `connectors/{connector_name}/`
- Each connector has its own `README.md`, `__init__.py`, and test file
- Use `.env.example` for configuration templates — NEVER hardcode secrets
- Test with synthetic data — NEVER commit real health data

### File Structure (for connectors)
```
connectors/my_connector/
├── README.md           # What it does, how to configure
├── __init__.py         # Main connector implementation
├── types.py            # Connector-specific types (if needed)
├── utils.py            # Helper functions (if needed)
├── .env.example        # Configuration template
└── tests/
    └── test_connector.py  # Tests
```

### Testing
- All logic must have tests
- Use unittest
- Test the happy path AND error cases
- Mock external APIs — don't call real services in tests
- Test data must be synthetic, never real health data

### Commits
- Use Conventional Commits: `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`
- Scope by area: `feat(connector):`, `fix(core):`, `docs(hypothesis):`
- Write clear commit messages explaining WHY, not just WHAT

## Security — NON-NEGOTIABLE

- **NEVER commit API keys, tokens, passwords, or any secrets**
- **NEVER commit real health data** — use synthetic test data only
- **NEVER disable security checks** — no `# noqa`, no `# type: ignore` for security rules
- Store all credentials in `.env` files (gitignored)
- Provide `.env.example` with placeholder values
- If you see a secret in code during review, flag it immediately

## Architecture Rules

- Core modules (`core/`) should have ZERO external dependencies beyond the standard lib and approved packages
- Connectors can have their own dependencies (listed in their own pyproject.toml or the root)
- All data flows through the `HealthEvent` schema — no connector-specific data formats in the core
- Privacy utilities in `core/privacy/` must be used for any data that leaves the local machine
- The hypothesis engine must anonymize all contributed data before storage

## What NOT to Do

- Don't add features to `core/` without an RFC
- Don't create new top-level directories without discussion
- Don't refactor other people's connectors without their approval
- Don't add cloud dependencies — everything must work offline
- Don't add telemetry or analytics of any kind
- Don't use `print()` for debugging — use the project logger (when implemented)

## PR Review Checklist

When reviewing AI-generated code, verify:
1. Does it implement the correct interface?
2. Are there tests?
3. Any hardcoded secrets or real data?
4. Does it handle errors properly?
5. Is the code readable by a human (not just AI-generated spaghetti)?
6. Does it follow the file structure convention?
