import tempfile
import unittest
from pathlib import Path

from openhealth import index, modules
from openhealth.modules import medications  # noqa: F401  (import side-effect: registration)


def _module():
    return modules.get_module("medications")


class LedgerComputeTests(unittest.TestCase):
    def test_items_become_interventions_with_windows(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [
                {"name": "Magnesium", "kind": "supplement", "dose": "400 mg", "schedule": "evening",
                 "start_date": "2026-04-01", "source": "self"},
                {"name": "Smoking", "kind": "habit_bad", "start_date": "2020-01-01"},
                {"name": "Old med", "kind": "medication", "start_date": "2025-01-01",
                 "end_date": "2025-03-01", "status": "stopped", "source": "doctor"},
            ],
        })
        self.assertEqual(len(res.metrics), 3)
        by_subject = {m["subject"]: m for m in res.metrics}
        mag = by_subject["Magnesium"]
        self.assertEqual(mag["record_type"], "Intervention")
        self.assertEqual(mag["intervention_kind"], "supplement")
        self.assertEqual(mag["status"], "active")
        self.assertEqual(mag["dosage"], "400 mg")
        self.assertEqual(mag["cadence"], "evening")
        self.assertEqual(mag["start_date"], "2026-04-01")
        self.assertIsNone(mag["end_date"])
        self.assertEqual(mag["metadata"]["duration_months"], 2.0)
        # Stopped item keeps its end window and status.
        old = by_subject["Old med"]
        self.assertEqual(old["status"], "stopped")
        self.assertEqual(old["end_date"], "2025-03-01")
        self.assertEqual(old["metadata"]["source"], "doctor")
        # Habit rides intervention_kind "habit".
        self.assertEqual(by_subject["Smoking"]["intervention_kind"], "habit")

    def test_validation_rejects_bad_input(self):
        m = _module()
        with self.assertRaises(ValueError):
            m.compute({"items": []})
        with self.assertRaises(ValueError):
            m.compute({"items": [{"name": "X", "kind": "potion"}]})
        with self.assertRaises(ValueError):
            m.compute({"items": [{"name": "X", "kind": "medication", "status": "maybe"}]})
        with self.assertRaises(ValueError):
            m.compute({"items": [{"name": "X", "kind": "medication", "schedule": "midnight"}]})
        with self.assertRaises(ValueError):
            m.compute({"items": [{"name": "X", "kind": "medication", "start_date": "someday"}]})
        with self.assertRaises(ValueError):
            m.compute({"items": [{"name": "", "kind": "medication"}]})

    def test_missing_start_date_is_not_invented(self):
        res = _module().compute({"today": "2026-06-01", "items": [{"name": "Zinc", "kind": "supplement"}]})
        rec = res.metrics[0]
        self.assertIsNone(rec["start_date"])
        self.assertIsNone(rec["metadata"]["duration_months"])


class ReviewFlagTests(unittest.TestCase):
    def test_long_running_active_med_gets_c3_review_question(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [{"name": "Vitamin D", "kind": "supplement", "start_date": "2025-09-01"}],
        })
        reviews = [i for i in res.insights if i["id"].startswith("insight-medications-review-")]
        self.assertEqual(len(reviews), 1)
        rev = reviews[0]
        self.assertEqual(rev["record_type"], "InsightHypothesis")
        # C3 framing: labeled and phrased as a question, not advice.
        self.assertIn("[C3", rev["summary"])
        self.assertIn("?", rev["summary"])
        self.assertIn("see-clinician", rev["tags"])
        self.assertEqual(rev["evidence_record_ids"], ["intervention-supplement-vitamin-d"])

    def test_no_review_flag_below_threshold_or_for_stopped(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [
                {"name": "Fresh med", "kind": "medication", "start_date": "2026-05-01"},
                {"name": "Past med", "kind": "medication", "start_date": "2024-01-01",
                 "end_date": "2024-02-01", "status": "stopped"},
                {"name": "Smoking", "kind": "habit_bad", "start_date": "2020-01-01"},
            ],
        })
        self.assertEqual([i for i in res.insights if i["id"].startswith("insight-medications-review-")], [])

    def test_review_threshold_is_configurable(self):
        res = _module().compute({
            "today": "2026-06-01",
            "review_months": 1,
            "items": [{"name": "Magnesium", "kind": "supplement", "start_date": "2026-04-01"}],
        })
        self.assertEqual(len([i for i in res.insights if "review" in i["id"]]), 1)


class InteractionAndHabitTests(unittest.TestCase):
    def test_two_active_pharma_items_get_honest_interaction_disclaimer(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [
                {"name": "Med A", "kind": "medication"},
                {"name": "Supp B", "kind": "supplement"},
            ],
        })
        notes = [i for i in res.insights if i["id"] == "note-medications-interactions"]
        self.assertEqual(len(notes), 1)
        summary = notes[0]["summary"]
        # Honest: we do NOT check interactions; a human professional does.
        self.assertIn("does not check", summary)
        self.assertIn("pharmacist", summary)
        self.assertIn("see-clinician", notes[0]["tags"])

    def test_single_active_item_no_interaction_note(self):
        res = _module().compute({"today": "2026-06-01", "items": [{"name": "Med A", "kind": "medication"}]})
        self.assertEqual([i for i in res.insights if i["id"] == "note-medications-interactions"], [])

    def test_habits_link_to_journal_behaviors_for_correlations(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [
                {"name": "Alcohol", "kind": "habit_bad"},  # resolves by name in the journal catalog
                {"name": "Doomscrolling", "kind": "habit_bad"},  # no catalog match
                {"name": "Meditation", "kind": "habit_good", "behavior_id": "recovery_activities.meditation"},
            ],
        })
        links = [i for i in res.insights if i["note_kind"] == "medications_journal_link" if "note_kind" in i]
        self.assertEqual(len(links), 1)
        candidates = {c["name"]: c for c in links[0]["metadata"]["candidates"]}
        self.assertEqual(candidates["Alcohol"]["behavior_id"], "lifestyle.alcohol")
        self.assertTrue(candidates["Meditation"]["matched"])
        self.assertEqual(candidates["Meditation"]["behavior_id"], "recovery_activities.meditation")
        self.assertFalse(candidates["Doomscrolling"]["matched"])
        self.assertIn("correlations-candidate", links[0]["tags"])

    def test_snapshot_note_counts_active_by_kind(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [
                {"name": "Med A", "kind": "medication"},
                {"name": "Supp B", "kind": "supplement", "status": "paused"},
                {"name": "Smoking", "kind": "habit_bad"},
            ],
        })
        snap = [i for i in res.insights if i.get("note_kind") == "medications_snapshot"][0]
        self.assertEqual(
            snap["metadata"]["counts"], {"medication": 1, "supplement": 0, "habit_bad": 1, "habit_good": 0}
        )
        self.assertEqual(snap["metadata"]["total_items"], 3)


class PersistAndRegistryTests(unittest.TestCase):
    def test_module_self_registers(self):
        m = _module()
        self.assertEqual(m.domain, "medications")
        self.assertIn("required", m.schema())

    def test_persist_writes_to_index(self):
        res = _module().compute({
            "today": "2026-06-01",
            "items": [{"name": "Magnesium", "kind": "supplement", "start_date": "2026-04-01"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            written = medications.persist(res, db)
            self.assertEqual(written, len(res.metrics) + len(res.insights))
            self.assertEqual(len(index.list_records(db, "Intervention")), 1)


if __name__ == "__main__":
    unittest.main()
