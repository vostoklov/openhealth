import os
import tempfile
import unittest
from pathlib import Path

from openhealth import index, modules
from openhealth.modules import nutrition  # noqa: F401  (import side-effect: registration)


def _module():
    return modules.get_module("nutrition")


class StyleSetupTests(unittest.TestCase):
    def test_full_profile_round_trip(self):
        rec = nutrition.setup_style({
            "pattern": "intermittent_fasting",
            "meals_per_day": 2,
            "eating_window": {"start": "12:00", "end": "20:00"},
            "caffeine": {"servings_per_day": 2, "last_time": "14:00"},
            "alcohol_frequency": "rare",
            "sugary_drinks": False,
            "water_liters_per_day": 2.5,
            "bad_habits": "late-night snacking",
        })
        self.assertEqual(rec["id"], "nutrition-style")  # stable id -> upsert updates in place
        self.assertEqual(rec["record_type"], "ContextNote")
        self.assertEqual(rec["note_kind"], "nutrition_style")
        profile = nutrition.profile_from_record(rec)
        self.assertEqual(profile["pattern"], "intermittent_fasting")
        self.assertEqual(profile["eating_window"], {"start": "12:00", "end": "20:00", "hours": 8.0})
        self.assertEqual(profile["caffeine"]["last_time"], "14:00")
        self.assertEqual(profile["bad_habits"], "late-night snacking")

    def test_minimal_profile_defaults(self):
        rec = nutrition.setup_style({"pattern": "omnivore", "meals_per_day": 3})
        profile = nutrition.profile_from_record(rec)
        self.assertIsNone(profile["eating_window"])
        self.assertEqual(profile["alcohol_frequency"], "none")
        self.assertFalse(profile["sugary_drinks"])
        self.assertIsNone(profile["bad_habits"])
        self.assertIsNone(nutrition.profile_from_record(None))

    def test_validation(self):
        with self.assertRaises(ValueError):
            nutrition.setup_style({"pattern": "carnivore", "meals_per_day": 3})
        with self.assertRaises(ValueError):
            nutrition.setup_style({"pattern": "omnivore", "meals_per_day": 0})
        with self.assertRaises(ValueError):
            nutrition.setup_style({
                "pattern": "omnivore", "meals_per_day": 3,
                "eating_window": {"start": "20:00", "end": "12:00"},
            })
        with self.assertRaises(ValueError):
            nutrition.setup_style({"pattern": "omnivore", "meals_per_day": 3, "alcohol_frequency": "sometimes"})


class MealLogTests(unittest.TestCase):
    def test_meals_become_observations_and_window(self):
        res = _module().compute({
            "date": "2026-06-01",
            "meals": [
                {"time": "09:30", "meal": "breakfast", "text": "oats"},
                {"time": "13:00", "meal": "lunch"},
                {"time": "19:30", "meal": "dinner", "tags": ["restaurant"]},
            ],
        })
        meal_obs = [m for m in res.metrics if m["observation_kind"] == "meal"]
        self.assertEqual(len(meal_obs), 3)
        self.assertEqual(meal_obs[0]["metadata"]["text"], "oats")
        self.assertIn("restaurant", meal_obs[2]["tags"])

        window = [m for m in res.metrics if m["observation_kind"] == "eating_window"][0]
        self.assertEqual(window["value"], 10.0)  # 09:30 -> 19:30
        self.assertEqual(window["metadata"]["first_meal"], "09:30")
        self.assertEqual(window["metadata"]["last_meal"], "19:30")
        self.assertEqual(window["metadata"]["by_meal"], {"breakfast": 1, "lunch": 1, "dinner": 1})

        day_note = [i for i in res.insights if i.get("note_kind") == "nutrition_day"]
        self.assertEqual(len(day_note), 1)

    def test_validation(self):
        m = _module()
        with self.assertRaises(ValueError):
            m.compute({"meals": []})
        with self.assertRaises(ValueError):
            m.compute({"meals": [{"time": "09:00", "meal": "brunch"}]})
        with self.assertRaises(ValueError):
            m.compute({"meals": [{"time": "9 am", "meal": "breakfast"}]})
        with self.assertRaises(ValueError):
            m.compute({"date": "not-a-date", "meals": [{"time": "09:00", "meal": "breakfast"}]})


class LateEatingTests(unittest.TestCase):
    def test_late_meal_inside_wind_down_raises_c3_question(self):
        res = _module().compute({
            "date": "2026-06-01",
            "bedtime": "23:00",
            "meals": [
                {"time": "12:00", "meal": "lunch"},
                {"time": "21:30", "meal": "dinner"},  # inside 21:00-23:00 wind-down
            ],
        })
        late = [i for i in res.insights if i["id"].startswith("insight-nutrition-late-eating")]
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0]["record_type"], "InsightHypothesis")
        self.assertIn("[C3", late[0]["summary"])
        self.assertIn("?", late[0]["summary"])  # framed as a question, not a verdict
        self.assertEqual(late[0]["metadata"]["wind_down_start"], "21:00")
        self.assertTrue(late[0]["open_questions"])  # confounders are asked about

    def test_early_last_meal_no_flag(self):
        res = _module().compute({
            "date": "2026-06-01",
            "bedtime": "23:00",
            "meals": [{"time": "12:00", "meal": "lunch"}, {"time": "19:00", "meal": "dinner"}],
        })
        self.assertEqual([i for i in res.insights if "late-eating" in i.get("tags", [])], [])

    def test_no_bedtime_no_flag(self):
        res = _module().compute({
            "date": "2026-06-01",
            "meals": [{"time": "23:30", "meal": "snack"}],
        })
        self.assertEqual([i for i in res.insights if "late-eating" in i.get("tags", [])], [])

    def test_after_midnight_bedtime_belongs_to_same_evening(self):
        res = _module().compute({
            "date": "2026-06-01",
            "bedtime": "00:30",  # 24:30 internally; wind-down starts 22:30
            "meals": [{"time": "23:00", "meal": "snack"}],
        })
        late = [i for i in res.insights if i["id"].startswith("insight-nutrition-late-eating")]
        self.assertEqual(len(late), 1)
        self.assertEqual(late[0]["metadata"]["wind_down_start"], "22:30")


class WindowDriftTests(unittest.TestCase):
    def test_actual_window_outside_declared_raises_c2_question(self):
        profile = nutrition.profile_from_record(nutrition.setup_style({
            "pattern": "intermittent_fasting",
            "meals_per_day": 2,
            "eating_window": {"start": "12:00", "end": "20:00"},
        }))
        res = _module().compute({
            "date": "2026-06-01",
            "profile": profile,
            "meals": [{"time": "10:00", "meal": "breakfast"}, {"time": "19:00", "meal": "dinner"}],
        })
        drift = [i for i in res.insights if i["id"].startswith("insight-nutrition-window-drift")]
        self.assertEqual(len(drift), 1)
        self.assertIn("[C2", drift[0]["summary"])
        self.assertEqual(drift[0]["metadata"]["actual"], {"start": "10:00", "end": "19:00"})

    def test_inside_declared_window_no_drift(self):
        profile = {"eating_window": {"start": "12:00", "end": "20:00"}}
        res = _module().compute({
            "date": "2026-06-01",
            "profile": profile,
            "meals": [{"time": "12:30", "meal": "lunch"}, {"time": "19:00", "meal": "dinner"}],
        })
        self.assertEqual([i for i in res.insights if "drift" in i.get("tags", [])], [])


class PhotoIntakeAndPersistTests(unittest.TestCase):
    def test_store_meal_photo_is_immutable_and_content_addressed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            photo = root / "lunch.jpg"
            photo.write_bytes(b"\xff\xd8\xff fake jpeg")
            archived = nutrition.store_meal_photo(root, photo, day="2026-06-01")
            archived_path = Path(archived)
            self.assertTrue(archived_path.exists())
            self.assertTrue(str(archived_path).startswith(str(root / "data" / "sources" / "nutrition")))
            self.assertTrue(archived_path.name.startswith("2026-06-01-meal-lunch-"))
            self.assertFalse(os.access(str(archived_path), os.W_OK))
            # Re-storing the same photo is a no-op (same path back).
            self.assertEqual(nutrition.store_meal_photo(root, photo, day="2026-06-01"), archived)
            with self.assertRaises(ValueError):
                nutrition.store_meal_photo(root, root / "missing.jpg")

    def test_persist_writes_day_and_style_to_index(self):
        style = nutrition.setup_style({"pattern": "omnivore", "meals_per_day": 3})
        res = _module().compute({
            "date": "2026-06-01",
            "meals": [{"time": "09:00", "meal": "breakfast"}],
        })
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            nutrition.persist_style(style, db)
            written = nutrition.persist(res, db)
            self.assertEqual(written, len(res.metrics) + len(res.insights))
            self.assertEqual(len(index.list_records(db, "Observation")), 2)  # meal + window
            notes = index.list_records(db, "ContextNote")
            self.assertEqual({n["id"] for n in notes}, {"nutrition-style", "nutrition-day-2026-06-01"})

    def test_module_self_registers(self):
        m = _module()
        self.assertEqual(m.domain, "nutrition")
        self.assertIn("meals", m.schema()["properties"])


if __name__ == "__main__":
    unittest.main()
