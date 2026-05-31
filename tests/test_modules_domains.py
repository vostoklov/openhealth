import unittest

from openhealth import modules
from openhealth.modules import sleep, cycle, body


class SleepModuleTests(unittest.TestCase):
    def test_session_markers_exact(self):
        mk = sleep.session_markers("2024-06-01T23:00:00", "2024-06-02T07:00:00")
        self.assertAlmostEqual(mk["duration_h"], 8.0, places=6)
        self.assertAlmostEqual(mk["midsleep_clock_h"], 3.0, places=6)  # 23:00 + 4h = 03:00
        self.assertAlmostEqual(mk["dlmo_proxy_clock_h"], 21.0, places=6)  # 23 - 2

    def test_social_jetlag(self):
        sessions = [
            {"onset": "2024-06-03T23:00:00", "offset": "2024-06-04T07:00:00", "workday": True},
            {"onset": "2024-06-07T01:00:00", "offset": "2024-06-07T10:00:00", "workday": False},
        ]
        sj = sleep.social_jetlag(sessions)
        # work midsleep 03:00, free midsleep 05:30 -> 2.5 h
        self.assertAlmostEqual(sj["social_jetlag_h"], 2.5, places=6)

    def test_module_compute_caps_phase(self):
        modules.load_builtin()
        m = modules.get_module("sleep")
        res = m.compute({"sessions": [{"onset": "2024-06-01T23:00:00", "offset": "2024-06-02T07:00:00", "date": "2024-06-01"}]})
        self.assertEqual(len(res.metrics), 1)
        phase = [i for i in res.insights if "circadian" in i["tags"]][0]
        self.assertLessEqual(phase["confidence"], 0.45)
        self.assertIn("?", phase["summary"])


class CycleModuleTests(unittest.TestCase):
    def test_cycle_lengths(self):
        starts = ["2024-01-01", "2024-01-29", "2024-02-26"]  # 28, 28
        self.assertEqual(cycle.cycle_lengths(starts), [28, 28])

    def test_prediction_and_fertile_window(self):
        modules.load_builtin()
        m = modules.get_module("cycle")
        res = m.compute({"period_starts": ["2024-01-01", "2024-01-29", "2024-02-26", "2024-03-25"]})
        pred = [i for i in res.insights if i["id"] == "insight-cycle-prediction"][0]
        # last 2024-03-25 + 28 = 2024-04-22; ovulation -14 = 2024-04-08
        self.assertEqual(pred["metadata"]["next_period"], "2024-04-22")
        self.assertEqual(pred["metadata"]["fertile_end"], "2024-04-09")  # ovulation +1
        self.assertLessEqual(pred["confidence"], 0.45)  # never high

    def test_irregular_raises_clinician_prompt(self):
        modules.load_builtin()
        m = modules.get_module("cycle")
        res = m.compute({"period_starts": ["2024-01-01", "2024-01-15", "2024-03-01"]})  # 14, 46 -> irregular
        self.assertTrue(any("see-clinician" in i.get("tags", []) for i in res.insights))


class BodyModuleTests(unittest.TestCase):
    def test_weight_trend_down(self):
        weights = [
            {"date": "2024-06-01", "kg": 80.0},
            {"date": "2024-06-08", "kg": 79.5},
            {"date": "2024-06-15", "kg": 79.0},
            {"date": "2024-06-22", "kg": 78.5},
        ]
        wt = body.weight_trend(weights)
        self.assertEqual(wt["latest_kg"], 78.5)
        self.assertAlmostEqual(wt["trend_kg_per_week"], -0.5, places=3)

    def test_longest_fast(self):
        eat = ["2024-06-01T20:00:00", "2024-06-02T12:00:00", "2024-06-02T13:00:00"]
        self.assertAlmostEqual(body.longest_fast_h(eat), 16.0, places=3)

    def test_habit_streak(self):
        self.assertEqual(body.habit_streak(["2024-06-01", "2024-06-02", "2024-06-03"]), 3)
        self.assertEqual(body.habit_streak(["2024-06-01", "2024-06-03"]), 1)  # gap breaks streak

    def test_module_compute(self):
        modules.load_builtin()
        m = modules.get_module("body")
        res = m.compute({
            "weights": [{"date": "2024-06-01", "kg": 80}, {"date": "2024-06-08", "kg": 79}],
            "eat_events": ["2024-06-01T20:00:00", "2024-06-02T12:00:00"],
            "habit_days": ["2024-06-07", "2024-06-08"],
        })
        kinds = {mm["observation_kind"] for mm in res.metrics}
        self.assertEqual(kinds, {"weight", "fasting_window", "habit_streak"})


class RegistryTests(unittest.TestCase):
    def test_all_domains_registered(self):
        modules.load_builtin()
        ids = {m.id for m in modules.all_modules()}
        self.assertTrue({"pulse", "sleep", "cycle", "body"}.issubset(ids))


if __name__ == "__main__":
    unittest.main()
