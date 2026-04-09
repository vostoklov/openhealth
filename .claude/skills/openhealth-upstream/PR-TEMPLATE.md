# PR Body Template

Use this as the exact `--body` passed to `gh pr create` in Phase 6 of the `openhealth-upstream` workflow. Fill in every section. Do **not** remove the sanitization audit checklist — reviewers need to see what was verified.

Do **not** include:

- The path to the contributor's personal repo
- The contributor's real name, email, or username in the body text
- Any timestamps, dates, or locations from the contributor's own history

---

## Template (copy everything below into the PR body)

```markdown
## Summary

<!-- One or two sentences: what does this PR add, fix, or change? -->

## What was upstreamed

<!-- Bullet list of the new files and their purpose. Examples:
- `connectors/oura/connector.py` — new Oura ring daily summary connector
- `tests/test_oura_connector.py` — synthetic-data unit tests
- `openhealth/config.py` — adds `"oura"` to `SOURCE_TYPES`
-->

## Why

<!-- Link to the issue or RFC that motivates this change.
     core/ changes require an RFC — see CONTRIBUTING.md. -->

Closes #<issue-number>

## Origin

Ported from a contributor's private health workspace following the
`openhealth-upstream` skill (`.claude/skills/openhealth-upstream/`).
No personal data is included. No real fixtures were copied. All
test data is synthetic.

## Sanitization audit

I ran the full `openhealth-upstream` Phase 2 and Phase 5 checks. Every
item below was verified before staging.

**Phase 2 — pre-copy audit**
- [ ] Every candidate file was classified SAFE / NEEDS-SANITIZATION / NEVER-PORT
- [ ] Every NEVER-PORT file was explicitly excluded (not silently filtered)
- [ ] No files from `data/raw/`, `data/processed/`, or `data/index/` were considered

**Phase 4 — transforms applied**
- [ ] `owner=`/`"author":` values replaced with `"user"`
- [ ] Imports rewritten to `openhealth.*`
- [ ] Env vars rewritten to `OPENHEALTH_*`
- [ ] Personal file paths removed or parameterized
- [ ] Hardcoded locations removed or parameterized
- [ ] Personal comments and docstring examples stripped
- [ ] All fixtures are synthetic — no real CSV/JSON reused
- [ ] Types align with `openhealth/models.py` dataclasses
- [ ] Type hints on every public function (no `Any`)

**Phase 5 — leak grep on staged diff (all returned zero lines)**
- [ ] No real names
- [ ] No email addresses
- [ ] No `access_token` / `refresh_token` / `client_secret` / `Bearer` headers
- [ ] No `/Users/<name>/` paths
- [ ] No `HEALTH_OS_` env prefix (old name)
- [ ] No long hex blobs (potential keys)
- [ ] `ruff check .` clean
- [ ] `python -m unittest discover` clean
- [ ] `trufflehog` clean (if installed locally)

## What was intentionally omitted

<!-- Describe categories, not specific files. Examples:
- Raw WHOOP API response fixtures (regenerated synthetically)
- Any OAuth token caches
- Personal weather enrichment defaults (now a function parameter)
-->

## How to test

<!-- Step-by-step so a reviewer can verify end-to-end. Examples:
1. `pip install -e .[dev]`
2. `python -m unittest tests.test_oura_connector`
3. `openhealth ingest --source oura --path tests/fixtures/oura_synthetic.json`
-->

## Review routing

Per `CONTRIBUTING.md`:

- [ ] `connectors/<name>/` — 1 review from core team
- [ ] `core/` — 2 reviews + BDFL (requires linked RFC)
- [ ] `hypotheses/` — 1 review
- [ ] `docs/` — 1 review

## Checklist

- [ ] Follows the connector template (if a connector)
- [ ] Includes tests with synthetic data
- [ ] Passes `ruff check .`
- [ ] Passes `python -m unittest discover`
- [ ] No secrets, API keys, tokens, or real data
- [ ] Branch follows `CONTRIBUTING.md` naming
- [ ] Commit message is Conventional Commits
```
