---
description: Show recent insights across all domains, with confidence labels.
---

Use the **health-agent** skill. Run:

`python -m openhealth recent --type InsightHypothesis --limit 10`
`python -m openhealth recent --type PatternAlert --limit 10`

Read each back plainly with its C-label, keeping question framing for C3 and
below. Pin any `see-clinician` / red-flag alerts to the top and pass them
through without interpreting. End with one gentle next step.
