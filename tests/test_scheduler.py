import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from openhealth import index, scheduler
from openhealth.storage import build_paths

# A fixed "as of" so ISO-week keys and date math are deterministic.
AS_OF = "2026-06-09"  # Tuesday, ISO week 2026-W24


def _seed_whoop_week(db_path: Path, as_of: date, *, base_hrv=50.0):
    """Seed 7 days of WHOOP-shaped HRV + RHR records ending at ``as_of``.

    HRV climbs across the week so each day has a positive deviation from its own
    trailing baseline -> a clean recovery score every day.
    """
    for offset in range(6, -1, -1):
        day = (as_of - timedelta(days=offset)).isoformat()
        hrv = base_hrv + (6 - offset)  # 50,51,...,56
        index.upsert_record(db_path, {
            "id": "whoop-recovery-%s-hrv" % day,
            "record_type": "Observation", "source_id": "whoop",
            "title": "h", "summary": "s", "artifact_ids": [],
            "evidence_class": "personal", "confidence": 0.96, "date": day,
            "observation_kind": "whoop_recovery_metric", "metric_name": "hrv_rmssd",
            "value": hrv, "unit": "ms",
        })
        index.upsert_record(db_path, {
            "id": "whoop-recovery-%s-rhr" % day,
            "record_type": "Observation", "source_id": "whoop",
            "title": "h", "summary": "s", "artifact_ids": [],
            "evidence_class": "personal", "confidence": 0.96, "date": day,
            "observation_kind": "whoop_recovery_metric", "metric_name": "resting_heart_rate",
            "value": 55.0, "unit": "bpm",
        })


def _seed_correlation_history(db_path: Path, as_of: date):
    """Seed a behavior with a clear negative impact, well above the 5/5 threshold.

    6 yes-days (recovery 50) alternating with 6 no-days (recovery 65) within the
    90-day window, each carrying a recovery_score observation so correlations'
    from_index can pair them. Alternating -> many switches -> reaches C3.
    """
    day_cursor = as_of - timedelta(days=40)  # comfortably inside the 90d window
    flip = True
    for _ in range(12):
        d = day_cursor.isoformat()
        rec = 50.0 if flip else 65.0
        index.upsert_record(db_path, {
            "id": "obs-journal-%s-lifestyle.alcohol" % d,
            "record_type": "Observation", "source_id": "journal",
            "title": "j", "summary": "s", "artifact_ids": [],
            "evidence_class": "personal", "confidence": 0.9, "date": d,
            "observation_kind": "journal_entry", "metric_name": "lifestyle.alcohol",
            "value": flip,
            "metadata": {"behavior_id": "lifestyle.alcohol", "category": "lifestyle"},
        })
        index.upsert_record(db_path, {
            "id": "obs-recovery-score-%s" % d,
            "record_type": "Observation", "source_id": "recovery",
            "title": "r", "summary": "s", "artifact_ids": [],
            "evidence_class": "derived-metric", "confidence": 0.9, "date": d,
            "observation_kind": "recovery_score", "metric_name": "recovery_score",
            "value": rec,
        })
        flip = not flip
        day_cursor += timedelta(days=1)


class WeeklyDigestTests(unittest.TestCase):
    def _make_workspace(self):
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        paths = build_paths(root)
        paths.data_index.mkdir(parents=True, exist_ok=True)
        index.init_db(paths.db_path)
        as_of = date.fromisoformat(AS_OF)
        _seed_whoop_week(paths.db_path, as_of)
        _seed_correlation_history(paths.db_path, as_of)
        return root, paths

    def test_digest_on_synthetic_data(self):
        root, paths = self._make_workspace()
        digest = scheduler.run_weekly(root, as_of=AS_OF)

        # Shape + week key.
        self.assertEqual(digest["status"], "ok")
        self.assertEqual(digest["week"], "2026-W24")
        self.assertEqual(digest["scheduler_version"], scheduler.SCHEDULER_VERSION)

        # Recovery summary: a score for all 7 seeded days.
        rec = digest["recovery"]
        self.assertEqual(rec["window_days"], 7)
        self.assertEqual(rec["days_with_score"], 7)
        self.assertEqual(rec["skipped_days"], [])
        self.assertIsNotNone(rec["mean_score"])
        self.assertIsNotNone(rec["latest_score"])
        self.assertEqual(len(rec["per_day"]), 7)

        # Correlations: the alternating alcohol behavior is surfaced and "new".
        cor = digest["correlations"]
        self.assertEqual(cor["behaviors_considered"], 1)
        self.assertGreaterEqual(cor["actionable_total"], 1)
        self.assertEqual(cor["new_count"], cor["actionable_total"])  # all new on first pass
        new_ids = {n["id"] for n in cor["new_insights"]}
        self.assertIn("insight-correlation-lifestyle.alcohol", new_ids)
        # Negative-impact behavior, phrased as a cautious prompt.
        alcohol = next(n for n in cor["new_insights"] if n["id"].endswith("lifestyle.alcohol"))
        self.assertEqual(alcohol["direction"], "negative")
        self.assertLess(alcohol["impact"], 0)

        # Headline reads cleanly.
        self.assertIn("Weekly pass:", digest["headline"])

    def test_digest_persisted_to_index_and_files(self):
        root, paths = self._make_workspace()
        scheduler.run_weekly(root, as_of=AS_OF)

        # Latest-digest snapshot file in data/index.
        latest = paths.data_index / scheduler.DIGEST_LATEST_FILENAME
        self.assertTrue(latest.exists())
        loaded = json.loads(latest.read_text(encoding="utf-8"))
        self.assertEqual(loaded["week"], "2026-W24")

        # History file has exactly one line for the week.
        history = paths.data_index / scheduler.DIGEST_HISTORY_FILENAME
        self.assertTrue(history.exists())
        history_lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(history_lines), 1)

        # A queryable digest record landed in the index.
        notes = index.list_records(paths.db_path, "ContextNote")
        digests = [n for n in notes if n.get("id") == "scheduler-digest-2026-W24"]
        self.assertEqual(len(digests), 1)
        self.assertIn("weekly-digest", digests[0]["tags"])

        # Recovery metrics for the week were persisted (recovery_score per day).
        obs = index.list_records(paths.db_path, "Observation")
        score_days = {
            o["date"] for o in obs
            if o.get("observation_kind") == "recovery_score" and o.get("source_id") == "recovery"
        }
        for offset in range(7):
            day = (date.fromisoformat(AS_OF) - timedelta(days=offset)).isoformat()
            self.assertIn(day, score_days)

    def test_idempotent_same_week_skips(self):
        root, paths = self._make_workspace()
        first = scheduler.run_weekly(root, as_of=AS_OF)
        self.assertEqual(first["status"], "ok")

        second = scheduler.run_weekly(root, as_of=AS_OF)
        self.assertEqual(second["status"], "skipped")
        self.assertEqual(second["week"], "2026-W24")

        # History still has a single line for the week (no duplication).
        history = paths.data_index / scheduler.DIGEST_HISTORY_FILENAME
        history_lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(history_lines), 1)

    def test_force_reruns_without_duplicating_history(self):
        root, paths = self._make_workspace()
        scheduler.run_weekly(root, as_of=AS_OF)
        forced = scheduler.run_weekly(root, as_of=AS_OF, force=True)
        self.assertEqual(forced["status"], "ok")

        history = paths.data_index / scheduler.DIGEST_HISTORY_FILENAME
        history_lines = [ln for ln in history.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(history_lines), 1)  # same week replaced, not appended

    def test_dry_run_writes_nothing(self):
        root, paths = self._make_workspace()
        digest = scheduler.run_weekly(root, as_of=AS_OF, persist=False)
        self.assertEqual(digest["status"], "ok")
        self.assertFalse((paths.data_index / scheduler.DIGEST_LATEST_FILENAME).exists())
        self.assertFalse((paths.data_index / scheduler.STATE_FILENAME).exists())

    def test_missing_hrv_days_are_skipped_not_fatal(self):
        # Fresh workspace with NO whoop data at all -> recovery summary empty,
        # the pass still completes and writes a digest.
        tmp = tempfile.mkdtemp()
        root = Path(tmp)
        paths = build_paths(root)
        paths.data_index.mkdir(parents=True, exist_ok=True)
        index.init_db(paths.db_path)

        digest = scheduler.run_weekly(root, as_of=AS_OF)
        self.assertEqual(digest["status"], "ok")
        self.assertEqual(digest["recovery"]["days_with_score"], 0)
        self.assertEqual(len(digest["recovery"]["skipped_days"]), 7)
        self.assertIsNone(digest["recovery"]["mean_score"])
        self.assertEqual(digest["correlations"]["new_count"], 0)


if __name__ == "__main__":
    unittest.main()
