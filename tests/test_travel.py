"""Tests for the Travel & Timezone module (self-contained, stdlib unittest)."""

import unittest

from openhealth.modules import travel
from openhealth.modules.base import all_modules, get_module, register


class AdaptationTests(unittest.TestCase):
    def test_eastward_slower_than_westward(self):
        # +8h east vs -8h west: same crossing, east should take >= west.
        east = travel.adaptation_days(8)
        west = travel.adaptation_days(-8)
        self.assertGreater(east, west)
        # east at 1.0 h/day -> 8 days; west at 1.5 h/day -> ceil(5.33) = 6.
        self.assertEqual(east, 8)
        self.assertEqual(west, 6)

    def test_sub_threshold_is_zero(self):
        self.assertEqual(travel.adaptation_days(0), 0)

    def test_cap(self):
        # Absurd 30h offset still capped.
        self.assertEqual(travel.adaptation_days(30), travel.MAX_ADAPT_DAYS)


class NormalizeTests(unittest.TestCase):
    def test_sorts_and_parses(self):
        periods = [
            {"start": "2024-06-10", "city": "Tbilisi", "tz_offset_hours": 4},
            {"start": "2024-06-01", "city": "Lisbon", "tz_offset_hours": 1, "end": "2024-06-09"},
        ]
        norm = travel.normalize_periods(periods)
        self.assertEqual([p["city"] for p in norm], ["Lisbon", "Tbilisi"])
        self.assertEqual(norm[0]["_end"].isoformat(), "2024-06-09")
        self.assertIsNone(norm[1]["_end"])  # ongoing stay

    def test_missing_fields_raise(self):
        with self.assertRaises(ValueError):
            travel.normalize_periods([{"start": "2024-06-01"}])  # no tz_offset_hours
        with self.assertRaises(ValueError):
            travel.normalize_periods([{"tz_offset_hours": 1}])  # no start

    def test_end_before_start_raises(self):
        with self.assertRaises(ValueError):
            travel.normalize_periods([
                {"start": "2024-06-10", "end": "2024-06-01", "tz_offset_hours": 0},
            ])

    def test_input_not_mutated(self):
        periods = [{"start": "2024-06-01", "tz_offset_hours": 1}]
        travel.normalize_periods(periods)
        self.assertNotIn("_start", periods[0])


class DetectShiftTests(unittest.TestCase):
    def setUp(self):
        # Lisbon (UTC+1) -> Tbilisi (UTC+4): east, 3h on 2024-06-10.
        self.periods = [
            {"start": "2024-06-01", "city": "Lisbon", "tz_offset_hours": 1, "end": "2024-06-09"},
            {"start": "2024-06-10", "city": "Tbilisi", "tz_offset_hours": 4},
        ]

    def test_detects_one_eastward_shift(self):
        shifts = travel.detect_shifts(self.periods)
        self.assertEqual(len(shifts), 1)
        s = shifts[0]
        self.assertEqual(s["direction"], "east")
        self.assertEqual(s["crossed_hours"], 3)
        self.assertEqual(s["delta_hours"], 3)
        self.assertEqual(s["from_city"], "Lisbon")
        self.assertEqual(s["to_city"], "Tbilisi")
        self.assertEqual(s["date"], "2024-06-10")
        # 3h east at 1.0 h/day -> 3 adaptation days.
        self.assertEqual(s["adaptation_days"], 3)
        self.assertEqual(s["adaptation_end"], "2024-06-12")

    def test_same_offset_no_shift(self):
        periods = [
            {"start": "2024-06-01", "tz_offset_hours": 2, "end": "2024-06-05"},
            {"start": "2024-06-06", "tz_offset_hours": 2},
        ]
        self.assertEqual(travel.detect_shifts(periods), [])

    def test_westward_direction(self):
        periods = [
            {"start": "2024-06-01", "tz_offset_hours": 4, "end": "2024-06-05"},
            {"start": "2024-06-06", "tz_offset_hours": 1},
        ]
        s = travel.detect_shifts(periods)[0]
        self.assertEqual(s["direction"], "west")
        self.assertEqual(s["delta_hours"], -3)
        self.assertEqual(s["crossed_hours"], 3)

    def test_jetlag_day_predicate(self):
        # Shift on 2024-06-10, 3 adaptation days -> 10,11,12 jetlagged.
        self.assertTrue(travel.is_jetlag_day(self.periods, "2024-06-10"))
        self.assertTrue(travel.is_jetlag_day(self.periods, "2024-06-12"))
        self.assertFalse(travel.is_jetlag_day(self.periods, "2024-06-13"))
        self.assertFalse(travel.is_jetlag_day(self.periods, "2024-06-05"))

    def test_location_on(self):
        self.assertEqual(travel.location_on(self.periods, "2024-06-03")["city"], "Lisbon")
        self.assertEqual(travel.location_on(self.periods, "2024-06-15")["city"], "Tbilisi")  # ongoing
        # Before any period -> uncovered.
        self.assertIsNone(travel.location_on(self.periods, "2024-05-01"))


class ModuleComputeTests(unittest.TestCase):
    def setUp(self):
        # Register manually: the module is intentionally not in load_builtin().
        if "travel" not in {m.id for m in all_modules()}:
            register(travel.TravelModule())
        self.module = get_module("travel")
        self.periods = [
            {"start": "2024-06-01", "city": "Lisbon", "tz_offset_hours": 1, "end": "2024-06-09"},
            {"start": "2024-06-10", "city": "Tbilisi", "tz_offset_hours": 4},
        ]

    def test_protocol_shape(self):
        self.assertEqual(self.module.id, "travel")
        self.assertEqual(self.module.domain, "journal")  # rides closest known domain
        self.assertIn("required", self.module.schema())

    def test_compute_emits_timeline_and_jetlag_context(self):
        res = self.module.compute({"periods": self.periods})
        kinds = {m["event_kind"] for m in res.metrics}
        self.assertEqual(kinds, {"location_period", "timezone_shift"})
        # Two stays + one shift = three timeline events.
        self.assertEqual(len(res.metrics), 3)

        # Exactly one jetlag ContextNote, evidence-gated and framed as a question.
        notes = [i for i in res.insights if i["record_type"] == "ContextNote"]
        self.assertEqual(len(notes), 1)
        note = notes[0]
        self.assertEqual(note["note_kind"], "jetlag")
        self.assertIn("context", note["tags"])
        self.assertLessEqual(note["confidence"], 0.45)  # never stated as fact
        self.assertIn("?", note["summary"])
        self.assertEqual(note["start_date"], "2024-06-10")
        self.assertEqual(note["end_date"], "2024-06-12")

    def test_compute_empty_raises(self):
        with self.assertRaises(ValueError):
            self.module.compute({"periods": []})


if __name__ == "__main__":
    unittest.main()
