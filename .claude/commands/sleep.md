---
description: Log last night's sleep and get duration, midsleep and a gentle circadian note.
argument-hint: "[when did you fall asleep / wake up?]"
---

Use the **health-agent** skill, domain `sleep`.

Ask plainly when they fell asleep and woke up (and whether it was a work day),
or read it from $ARGUMENTS. Build sessions and run:

`python -m openhealth module --id sleep --payload-json '{"sessions":[{"onset":"...","offset":"...","workday":true}]}'`

Read duration/midsleep as facts; the circadian phase is a rough behavioral
proxy — keep its question framing and C-label. Never diagnose.
