---
description: Log weight, meals (fasting) or a habit and see trend / streak.
argument-hint: "[weight, last meal time, or habit done]"
---

Use the **health-agent** skill, domain `body`.

Ask what they want to log — weight, meal times (for fasting window), or a habit
they did today — or read it from $ARGUMENTS. Accumulate with any prior data, then run:

`python -m openhealth module --id body --payload-json '{"weights":[{"date":"YYYY-MM-DD","kg":0}], "eat_events":["ISO"], "habit_days":["YYYY-MM-DD"]}'`

Report trend / fasting window / streak plainly. Any weight-trend insight keeps
its C-label and question framing. Never judge or diagnose.
