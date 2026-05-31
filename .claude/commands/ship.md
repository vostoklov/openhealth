---
description: Ship your change without touching git — the agent handles branch, commit, PR.
argument-hint: "[short description of what you changed]"
---

The person does not know git. Do it for them:

1. First run `make check` (lint + tests). If it fails, fix the issue with them
   in plain language before shipping — never ship red.
2. Then run `python scripts/oh_ship.py "<their description from $ARGUMENTS>"`.
   This makes a branch and commits locally. It only pushes / opens a PR with
   `--push` AND when the maintainer has set `OPENHEALTH_ALLOW_PUSH=1`.
3. Tell them in one friendly line what shipped and what happens next.

Never push to a public remote unless the maintainer has explicitly enabled it.
