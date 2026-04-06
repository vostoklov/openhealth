# Health OS — AI Development Rules

This file is read by AI coding tools (Claude Code, Cursor, Copilot, etc.) to ensure consistent code quality across all contributors.

## Project Overview

Health OS is a local-first, plugin-based personal health operating system. Data stays on the user's machine. Connectors pull data from external sources into a unified schema.

## Language & Standards

- **Language:** TypeScript (strict mode)
- **Runtime:** Node.js / Bun
- **Testing:** Vitest
- **Linting:** ESLint with strict config
- **Package manager:** npm

## Code Rules

### TypeScript
- `strict: true` in tsconfig — no exceptions
- Never use `any` — use `unknown` and narrow, or define proper types
- Use Zod schemas for runtime validation at system boundaries
- Prefer `interface` for public contracts, `type` for unions/intersections
- Export types explicitly — no `export *`

### Connectors
- Every connector MUST implement the `HealthConnector` interface from `core/schema`
- Connector code lives in `connectors/{connector-name}/`
- Each connector has its own `README.md`, `index.ts`, and test file
- Use `.env.example` for configuration templates — NEVER hardcode secrets
- Test with synthetic data — NEVER commit real health data

### File Structure (for connectors)
```
connectors/my-connector/
├── README.md           # What it does, how to configure
├── index.ts            # Main connector implementation
├── types.ts            # Connector-specific types (if needed)
├── utils.ts            # Helper functions (if needed)
├── .env.example        # Configuration template
└── __tests__/
    └── index.test.ts   # Tests
```

### Testing
- All logic must have tests
- Use Vitest
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
- **NEVER disable security checks** — no `// eslint-disable`, no `@ts-ignore` for security rules
- Store all credentials in `.env` files (gitignored)
- Provide `.env.example` with placeholder values
- If you see a secret in code during review, flag it immediately

## Architecture Rules

- Core modules (`core/`) should have ZERO external dependencies beyond the standard lib and approved packages
- Connectors can have their own dependencies (listed in their own package.json or the root)
- All data flows through the `HealthEvent` schema — no connector-specific data formats in the core
- Privacy utilities in `core/privacy/` must be used for any data that leaves the local machine
- The hypothesis engine must anonymize all contributed data before storage

## What NOT to Do

- Don't add features to `core/` without an RFC
- Don't create new top-level directories without discussion
- Don't refactor other people's connectors without their approval
- Don't add cloud dependencies — everything must work offline
- Don't add telemetry or analytics of any kind
- Don't use `console.log` for debugging — use the project logger (when implemented)

## PR Review Checklist

When reviewing AI-generated code, verify:
1. Does it implement the correct interface?
2. Are there tests?
3. Any hardcoded secrets or real data?
4. Does it handle errors properly?
5. Is the code readable by a human (not just AI-generated spaghetti)?
6. Does it follow the file structure convention?
