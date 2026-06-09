import tempfile
import unittest
from pathlib import Path

from openhealth import index, journal_behaviors, modules
from openhealth.modules import journal


class BehaviorCatalogTests(unittest.TestCase):
    def test_catalog_loads_and_has_categories(self):
        lib = journal_behaviors.library()
        self.assertEqual(lib["version"], 1)
        cat_ids = {c["id"] for c in journal_behaviors.categories()}
        self.assertEqual(
            cat_ids,
            {
                "health_symptoms",
                "hormonal_health",
                "lifestyle",
                "mental_wellbeing",
                "nutrition",
                "recovery_activities",
            },
        )

    def test_behaviors_nonempty_and_unique_ids(self):
        bs = journal_behaviors.all_behaviors()
        self.assertGreater(len(bs), 150)  # full WHOOP library, not a stub
        ids = [b["id"] for b in bs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_resolve_by_id_and_name(self):
        by_id = journal_behaviors.resolve("lifestyle.alcohol")
        by_name = journal_behaviors.resolve("Alcohol")
        self.assertIsNotNone(by_id)
        self.assertEqual(by_id["id"], by_name["id"])
        self.assertEqual(by_id["answer_type"], "boolean")
        self.assertIsNone(journal_behaviors.resolve("not-a-behavior"))


class JournalSetupTests(unittest.TestCase):
    def test_setup_valid_selection(self):
        rec = journal.setup(
            ["lifestyle.alcohol", "nutrition.breakfast", "recovery_activities.meditation"]
        )
        self.assertEqual(rec["record_type"], "ContextNote")
        self.assertEqual(rec["note_kind"], "journal_setup")
        self.assertEqual(len(rec["metadata"]["selected"]), 3)
        self.assertEqual(
            journal.active_behavior_ids(rec),
            ["lifestyle.alcohol", "nutrition.breakfast", "recovery_activities.meditation"],
        )

    def test_setup_rejects_too_few(self):
        with self.assertRaises(ValueError):
            journal.setup(["lifestyle.alcohol", "nutrition.breakfast"])

    def test_setup_rejects_too_many(self):
        with self.assertRaises(ValueError):
            journal.setup(
                [
                    "lifestyle.alcohol",
                    "nutrition.breakfast",
                    "recovery_activities.meditation",
                    "recovery_activities.sauna",
                    "lifestyle.outdoor_time",
                    "nutrition.added_sugar",
                ]
            )

    def test_setup_rejects_unknown_behavior(self):
        with self.assertRaises(ValueError):
            journal.setup(["lifestyle.alcohol", "nutrition.breakfast", "bogus.behavior"])


class JournalCheckinTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_checkin_produces_observations_and_note(self):
        m = modules.get_module("journal")
        res = m.compute(
            {
                "date": "2026-06-01",
                "entries": {"Alcohol": "no", "nutrition.breakfast": True},
            }
        )
        self.assertEqual(len(res.metrics), 2)
        self.assertEqual(len(res.insights), 1)  # the day note
        # Boolean coercion: "no" -> False, True stays True.
        by_metric = {x["metric_name"]: x["value"] for x in res.metrics}
        self.assertIs(by_metric["lifestyle.alcohol"], False)
        self.assertIs(by_metric["nutrition.breakfast"], True)
        for x in res.metrics:
            self.assertEqual(x["observation_kind"], "journal_entry")
            self.assertEqual(x["record_type"], "Observation")
        self.assertEqual(res.insights[0]["note_kind"], "journal_checkin")

    def test_checkin_defaults_to_today_and_validates_date(self):
        m = modules.get_module("journal")
        res = m.compute({"entries": {"Alcohol": False}})
        self.assertEqual(res.metrics[0]["date"], journal.today_iso())
        with self.assertRaises(ValueError):
            m.compute({"date": "not-a-date", "entries": {"Alcohol": False}})

    def test_checkin_requires_entries(self):
        m = modules.get_module("journal")
        with self.assertRaises(ValueError):
            m.compute({"date": "2026-06-01", "entries": {}})

    def test_yesterday_quick_entry_uses_earlier_date(self):
        m = modules.get_module("journal")
        res = m.compute({"date": journal.yesterday_iso(), "entries": {"Alcohol": True}})
        self.assertEqual(res.metrics[0]["date"], journal.yesterday_iso())
        self.assertNotEqual(journal.yesterday_iso(), journal.today_iso())

    def test_persist_writes_to_index(self):
        modules.load_builtin()
        m = modules.get_module("journal")
        res = m.compute({"date": "2026-06-01", "entries": {"Alcohol": False, "Meditation": True}})
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            written = journal.persist(res, db)
            self.assertEqual(written, 3)  # 2 obs + 1 note
            obs = index.list_records(db, "Observation")
            self.assertEqual(len(obs), 2)


if __name__ == "__main__":
    unittest.main()
