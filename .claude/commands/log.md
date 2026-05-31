---
description: Log anything — weight, cycle, food, sleep, mood, a photo or a note.
argument-hint: "[what happened]"
---

Use the **health-agent** skill. Read $ARGUMENTS, decide the domain (pulse /
sleep / cycle / body / metabolic / skin) or treat it as a free note, and route:
- structured signals -> the matching `python -m openhealth module --id <domain>`
- free text / voice / photo -> the existing intake pipeline (manual note or a
  telegram-intake style envelope) so it joins the timeline.

Confirm what you logged in one short line. Scan free text for red flags first.
Never diagnose.
