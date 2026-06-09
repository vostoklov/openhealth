# Weekly scheduler

`openhealth.scheduler` runs an unattended **weekly pass** over the local index:

1. **Recovery summary** — computes versioned recovery / strain / sleep-debt
   metrics for the last 7 days from indexed WHOOP data and persists them.
2. **New correlations** — recomputes behavior→recovery impacts and flags the
   ones that are *new* since the last pass.
3. **Digest** — writes a compact JSON digest into `data/index/` and a queryable
   digest record into the index.

Pure stdlib, zero external dependencies. Local-first: it reads and writes only
through the SQLite index, never the raw source files.

## Run it by hand

```bash
# Normal run (idempotent: a no-op if this ISO week was already processed)
python3 -m openhealth.scheduler --repo-root /path/to/openhealth

# Force a re-run for the current week
python3 -m openhealth.scheduler --repo-root /path/to/openhealth --force

# Backfill / test a specific week without writing anything
python3 -m openhealth.scheduler --repo-root /path/to/openhealth --as-of 2026-06-09 --dry-run
```

The command prints the digest as JSON and exits `0`. When the week was already
processed it prints `{"status": "skipped", ...}`.

## Outputs

Under `<repo>/data/index/`:

| File | Contents |
|------|----------|
| `weekly-digest.json` | Latest digest snapshot (overwritten each pass). |
| `weekly-digests.jsonl` | Append-only history, one line per ISO week (a re-run replaces that week's line, never duplicates it). |
| `scheduler_state.json` | Idempotency state: `last_week`, `last_run_at`. |

In the index: a `ContextNote` record `scheduler-digest-<ISO-week>` (tagged
`scheduler`, `weekly-digest`), visible via `openhealth recent`. Recovery metrics
and correlation insights land as their normal `Observation` /
`InsightHypothesis` records.

## Idempotency

The pass is keyed by **ISO year-week** (e.g. `2026-W24`). Running it any number
of times in the same week is a no-op unless `--force` is passed. All metric and
insight ids are deterministic, so even a forced re-run upserts in place rather
than creating duplicates. The state file is advanced **last**, so a crash
mid-pass simply re-runs cleanly on the next invocation.

## Schedule weekly: cron (Linux / generic Unix)

`crontab -e`, then add (runs every Monday at 07:30 local time):

```cron
30 7 * * 1 cd /path/to/openhealth && /usr/bin/python3 -m openhealth.scheduler --repo-root /path/to/openhealth >> /path/to/openhealth/data/index/scheduler.log 2>&1
```

Notes:
- Use an absolute `python3` path (`which python3`); cron has a minimal `PATH`.
- The pass is idempotent, so a daily cron entry is also fine — it only does real
  work once per ISO week. A daily trigger makes the run self-healing if the
  machine was asleep on Monday.

## Schedule weekly: launchd (macOS)

macOS deprecates user cron; prefer a LaunchAgent. Create
`~/Library/LaunchAgents/com.openhealth.scheduler.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.openhealth.scheduler</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>openhealth.scheduler</string>
    <string>--repo-root</string>
    <string>/path/to/openhealth</string>
  </array>

  <key>WorkingDirectory</key>
  <string>/path/to/openhealth</string>

  <!-- Monday 07:30 local time -->
  <key>StartCalendarInterval</key>
  <dict>
    <key>Weekday</key><integer>1</integer>
    <key>Hour</key><integer>7</integer>
    <key>Minute</key><integer>30</integer>
  </dict>

  <!-- If the Mac was asleep at the scheduled time, run at next wake. -->
  <key>RunAtLoad</key>
  <false/>

  <key>StandardOutPath</key>
  <string>/path/to/openhealth/data/index/scheduler.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/openhealth/data/index/scheduler.err.log</string>
</dict>
</plist>
```

Load / reload / unload:

```bash
launchctl unload ~/Library/LaunchAgents/com.openhealth.scheduler.plist 2>/dev/null
launchctl load   ~/Library/LaunchAgents/com.openhealth.scheduler.plist
launchctl start  com.openhealth.scheduler   # run once now to verify
```

`StartCalendarInterval` fires at the next opportunity if the machine was off or
asleep at the scheduled moment, and the pass's weekly idempotency makes that
catch-up safe.

## Exit codes

- `0` — pass completed (`status: "ok"`) or skipped (`status: "skipped"`).
- non-zero — unexpected error (check the log).
