"""Weekly auto-pass scheduler — recovery summary + new correlations + digest.

OpenHealth is agent-native and local-first. This module is the unattended
*weekly pass* that keeps the derived layer fresh without a human running
commands by hand:

1. **Recovery summary** — for each of the last 7 days, assemble a recovery
   payload from indexed WHOOP records (``modules.recovery.from_index``), compute
   the versioned recovery / strain / sleep-debt metrics, and persist them into
   the SQLite index. Aggregates the week into latest score, 7-day mean, and
   sleep-debt trend.
2. **New correlations** — recompute behavior→recovery impacts
   (``modules.correlations.from_index`` + ``analyze``) and surface only the
   insights that are *new* relative to what is already indexed, so the digest
   highlights what changed this week rather than repeating the whole list.
3. **Digest** — write a compact JSON digest into ``data/index`` (latest snapshot
   plus an append-only history keyed by ISO week) and persist a digest record
   into the index so it shows up via ``openhealth recent``.

Design rules honored here:

- **Idempotent.** The pass is keyed by ISO year-week. Running it twice in the
  same week is a no-op (returns ``status: "skipped"``) unless ``force=True``.
  Metric / insight ids are deterministic, so even a forced re-run upserts in
  place rather than duplicating.
- **Read through the index only.** Raw source files stay immutable; the
  scheduler reads and writes exclusively through ``openhealth.index``.
- **Cautious.** Correlations stay graded and capped by ``openhealth.evidence``;
  nothing here diagnoses or prescribes. It surfaces prompts for review.
- **Pure stdlib, zero external deps** (core rule). Wire it to ``cron`` or
  ``launchd`` per ``docs/scheduler.md``.
"""

import json
from datetime import date as _date
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import index
from . import modules as modpkg
from .storage import ensure_repo_structure, write_json

# Bump when the digest shape or pass semantics change in a breaking way.
SCHEDULER_VERSION = "weekly@v1"

# How many trailing days the recovery summary covers (one week).
RECOVERY_WINDOW_DAYS = 7

# Filenames written under data/index.
STATE_FILENAME = "scheduler_state.json"
DIGEST_LATEST_FILENAME = "weekly-digest.json"
DIGEST_HISTORY_FILENAME = "weekly-digests.jsonl"

# source_id used for the digest record persisted into the index.
DIGEST_SOURCE_ID = "scheduler"


# --- helpers ---------------------------------------------------------------

def _utc_today() -> _date:
    return datetime.now(timezone.utc).date()


def week_key(day: _date) -> str:
    """ISO year-week key, e.g. ``2026-W23``. The idempotency unit of the pass."""
    iso_year, iso_week, _ = day.isocalendar()
    return "%04d-W%02d" % (iso_year, iso_week)


def _last_n_days(as_of: _date, n: int) -> List[str]:
    """ISO date strings for the ``n`` days ending at (and including) ``as_of``."""
    return [(as_of - timedelta(days=offset)).isoformat() for offset in range(n - 1, -1, -1)]


def _read_state(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def _existing_correlation_ids(db_path: Path) -> set:
    """Ids of correlation insights already in the index (to detect what's new)."""
    existing = set()
    for rec in index.list_records(db_path, "InsightHypothesis"):
        rid = rec.get("id")
        if rid and rec.get("source_id") == "correlations":
            existing.add(rid)
    return existing


# --- recovery summary ------------------------------------------------------

def build_recovery_summary(
    db_path: Path,
    as_of: _date,
    *,
    persist: bool = True,
    baseline_window_days: int = 60,
) -> Dict[str, Any]:
    """Compute + (optionally) persist recovery metrics for the trailing week.

    Returns an aggregate summary dict. Days without HRV in the index are skipped
    gracefully (recorded under ``skipped_days``) rather than raising.
    """
    modpkg.load_builtin()
    from .modules import recovery

    module = modpkg.get_module("recovery")

    days = _last_n_days(as_of, RECOVERY_WINDOW_DAYS)
    per_day: List[Dict[str, Any]] = []
    skipped: List[str] = []
    written = 0

    for day in days:
        payload = recovery.from_index(db_path, day, baseline_window_days=baseline_window_days)
        if payload.get("hrv_ms") is None or payload.get("baseline_hrv_ms") is None:
            skipped.append(day)
            continue
        result = module.compute(payload)
        if persist:
            written += recovery.persist(result, db_path)
        score_metric = next((m for m in result.metrics if m.get("metric_name") == "recovery_score"), None)
        debt_metric = next((m for m in result.metrics if m.get("metric_name") == "sleep_debt_h"), None)
        per_day.append({
            "date": day,
            "recovery_score": score_metric["value"] if score_metric else None,
            "sleep_debt_h": debt_metric["value"] if debt_metric else None,
        })

    scores = [d["recovery_score"] for d in per_day if d["recovery_score"] is not None]
    debts = [d["sleep_debt_h"] for d in per_day if d["sleep_debt_h"] is not None]

    summary: Dict[str, Any] = {
        "window_days": RECOVERY_WINDOW_DAYS,
        "from": days[0],
        "to": days[-1],
        "days_with_score": len(scores),
        "skipped_days": skipped,
        "latest_score": per_day[-1]["recovery_score"] if per_day else None,
        "mean_score": round(sum(scores) / len(scores), 1) if scores else None,
        "min_score": min(scores) if scores else None,
        "max_score": max(scores) if scores else None,
        "total_sleep_debt_h": round(sum(debts), 2) if debts else None,
        "per_day": per_day,
        "metrics_written": written,
    }
    return summary


# --- correlations ----------------------------------------------------------

def build_correlations_update(
    db_path: Path,
    as_of: _date,
    *,
    persist: bool = True,
    window_days: int = 90,
) -> Dict[str, Any]:
    """Recompute behavior→recovery impacts and report which insights are new.

    "New" = an insight id not already present in the index before this pass.
    Returns the new insights plus a small roll-up; all insights are persisted
    (upserted) so existing ones stay current.
    """
    modpkg.load_builtin()
    from .modules import correlations

    module = modpkg.get_module("correlations")

    before = _existing_correlation_ids(db_path)

    behaviors = correlations.from_index(db_path, window_days=window_days, as_of=as_of.isoformat())
    result = module.compute({"behaviors": behaviors, "window_days": window_days})

    written = 0
    if persist and result.insights:
        written = correlations.persist(result, db_path)

    new_insights = [ins for ins in result.insights if ins.get("id") not in before]
    update: Dict[str, Any] = {
        "window_days": window_days,
        "behaviors_considered": len(behaviors),
        "actionable_total": len(result.insights),
        "new_count": len(new_insights),
        "insights_written": written,
        "new_insights": [
            {
                "id": ins.get("id"),
                "title": ins.get("title"),
                "summary": ins.get("summary"),
                "confidence": ins.get("confidence"),
                "confidence_grade": (ins.get("metadata") or {}).get("confidence_grade"),
                "impact": (ins.get("metadata") or {}).get("impact"),
                "direction": (ins.get("metadata") or {}).get("direction"),
            }
            for ins in new_insights
        ],
        "notes": result.notes,
    }
    return update


# --- digest record ---------------------------------------------------------

def _digest_headline(recovery_summary: Dict[str, Any], correlations_update: Dict[str, Any]) -> str:
    """One human-readable line summarizing the week (no diagnosis, no certainty)."""
    parts: List[str] = []
    mean = recovery_summary.get("mean_score")
    latest = recovery_summary.get("latest_score")
    if mean is not None:
        parts.append("recovery avg %.0f/100 (latest %.0f)" % (mean, latest if latest is not None else mean))
    else:
        parts.append("no recovery score this week")
    new_count = correlations_update.get("new_count", 0)
    if new_count:
        parts.append("%d new behavior pattern(s) to review" % new_count)
    else:
        parts.append("no new behavior patterns")
    return "Weekly pass: " + ", ".join(parts) + "."


def _digest_record(week: str, as_of: _date, headline: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """A ContextNote-shaped record for the index so the digest is queryable."""
    return {
        "id": "scheduler-digest-%s" % week,
        "record_type": "ContextNote",
        "source_id": DIGEST_SOURCE_ID,
        "title": "Weekly digest %s" % week,
        "summary": headline,
        "artifact_ids": [],
        "evidence_class": "derived-summary",
        "confidence": 0.6,
        "date": as_of.isoformat(),
        "tags": ["scheduler", "weekly-digest", "review-needed"],
        "metadata": {
            "week": week,
            "scheduler_version": SCHEDULER_VERSION,
            "recovery": payload["recovery"],
            "correlations": payload["correlations"],
        },
        "note_kind": "digest",
        "themes": ["recovery", "correlations"],
    }


# --- main entry point ------------------------------------------------------

def run_weekly(
    root: Path,
    *,
    as_of: Optional[str] = None,
    force: bool = False,
    persist: bool = True,
    correlations_window_days: int = 90,
    recovery_baseline_window_days: int = 60,
) -> Dict[str, Any]:
    """Run the weekly auto-pass. Idempotent per ISO week.

    Parameters
    ----------
    root: repository root (the OpenHealth workspace).
    as_of: optional ISO date (``YYYY-MM-DD``) to run *as if* it were that day;
        defaults to today (UTC). Useful for tests and backfills.
    force: re-run even if this ISO week was already processed.
    persist: write metrics/insights/digest into the index (set ``False`` for a
        dry run that only computes and returns the digest payload).

    Returns the digest dict. When skipped, returns ``{"status": "skipped", ...}``.
    """
    paths = ensure_repo_structure(root)
    index.init_db(paths.db_path)

    as_of_date = _date.fromisoformat(as_of) if as_of else _utc_today()
    week = week_key(as_of_date)

    state_path = paths.data_index / STATE_FILENAME
    state = _read_state(state_path)

    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    if not force and state.get("last_week") == week:
        return {
            "status": "skipped",
            "reason": "week %s already processed" % week,
            "week": week,
            "as_of": as_of_date.isoformat(),
            "last_run_at": state.get("last_run_at"),
            "scheduler_version": SCHEDULER_VERSION,
        }

    recovery_summary = build_recovery_summary(
        paths.db_path, as_of_date, persist=persist, baseline_window_days=recovery_baseline_window_days
    )
    correlations_update = build_correlations_update(
        paths.db_path, as_of_date, persist=persist, window_days=correlations_window_days
    )

    headline = _digest_headline(recovery_summary, correlations_update)
    payload = {"recovery": recovery_summary, "correlations": correlations_update}

    digest: Dict[str, Any] = {
        "status": "ok",
        "scheduler_version": SCHEDULER_VERSION,
        "week": week,
        "as_of": as_of_date.isoformat(),
        "generated_at": generated_at,
        "headline": headline,
        "recovery": recovery_summary,
        "correlations": correlations_update,
    }

    if persist:
        # Queryable digest record in the index.
        index.upsert_record(paths.db_path, _digest_record(week, as_of_date, headline, payload))

        # Latest-digest snapshot + append-only, idempotent history.
        write_json(paths.data_index / DIGEST_LATEST_FILENAME, digest)
        _append_history(paths.data_index / DIGEST_HISTORY_FILENAME, digest)

        # Advance idempotency state last, so a crash mid-pass re-runs cleanly.
        write_json(state_path, {
            "last_week": week,
            "last_run_at": generated_at,
            "scheduler_version": SCHEDULER_VERSION,
        })

    return digest


def _append_history(path: Path, digest: Dict[str, Any]) -> None:
    """Append one digest line per ISO week, replacing any prior line for that week.

    Keeps a compact, append-only audit trail without ever duplicating a week.
    """
    week = digest["week"]
    lines: List[str] = []
    if path.exists():
        for raw in path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                row = json.loads(raw)
            except ValueError:
                continue
            if row.get("week") == week:
                continue  # drop the stale entry for this week; we re-append below
            lines.append(json.dumps(row, ensure_ascii=False))
    lines.append(json.dumps(digest, ensure_ascii=False))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --- CLI -------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    """``python3 -m openhealth.scheduler [--repo-root .] [--as-of DATE] [--force] [--dry-run]``."""
    import argparse

    parser = argparse.ArgumentParser(
        prog="openhealth.scheduler",
        description="Weekly auto-pass: recovery summary + new correlations + digest.",
    )
    parser.add_argument("--repo-root", default=".", help="Path to the OpenHealth repository root.")
    parser.add_argument("--as-of", help="ISO date (YYYY-MM-DD) to run as if it were that day.")
    parser.add_argument("--force", action="store_true", help="Re-run even if this ISO week was already processed.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print the digest without writing anything.")
    args = parser.parse_args(argv)

    digest = run_weekly(
        Path(args.repo_root).resolve(),
        as_of=args.as_of,
        force=args.force,
        persist=not args.dry_run,
    )
    print(json.dumps(digest, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
