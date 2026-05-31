---
description: Show how one metric has moved over time.
argument-hint: "[metric, e.g. rmssd_ms, weight_kg, duration_h]"
---

Use the **health-agent** skill. Pick the metric from $ARGUMENTS (or ask), then:

`python -m openhealth recent --metric <metric_name> --limit 30`

Summarize the direction plainly ("up/down/steady, within your usual range").
Remind: look for repeating patterns, not single readings. No diagnosis.
