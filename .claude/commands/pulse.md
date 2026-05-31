---
description: Log a heart-rate / HRV reading and get a cautious readiness prompt.
argument-hint: "[paste RR intervals or describe your reading]"
---

Use the **health-agent** skill, domain `pulse`.

If the person pasted RR intervals or HRV data, build the payload from it.
Otherwise ask plainly for what they have (RR intervals in ms, or a wearable HRV
number) and, if known, their usual baseline RMSSD. Then run:

`python -m openhealth module --id pulse --payload-json '{...}'`

Read the metric back simply, then the readiness insight with its C-label and
question framing. Never diagnose. Context: $ARGUMENTS
