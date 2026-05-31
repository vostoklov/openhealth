---
description: Log period start dates and get cycle stats + a cautious next-period estimate.
argument-hint: "[period start dates]"
---

Use the **health-agent** skill, domain `cycle`.

Collect the first-day dates of recent periods (more dates = better estimate),
or read them from $ARGUMENTS. Run:

`python -m openhealth module --id cycle --payload-json '{"period_starts":["YYYY-MM-DD", ...]}'`

State clearly: this is a calendar estimate, **not contraception and not a
diagnosis**. Keep the C-label and question framing. If a see-clinician prompt
appears, pass it through plainly without interpreting.
