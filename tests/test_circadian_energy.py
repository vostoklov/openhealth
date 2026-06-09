"""Rise-style energy schedule tests (two-process model layer in circadian.py)."""

import unittest
from datetime import datetime, timedelta

from openhealth.circadian import (
    ENERGY_PHASE_INFO,
    day_phases,
    energy_curve,
    energy_schedule,
)

WAKE_7 = datetime(2026, 6, 10, 7, 0)
WAKE_9 = datetime(2026, 6, 10, 9, 0)
# Habitual bedtime 23:30 -> the anchor contract from compute_sleep_anchor.
ANCHOR_BED_2330 = {
    "bed_minutes": 23 * 60 + 30,
    "wake_minutes": 7 * 60,
    "midpoint_minutes": 3 * 60 + 15,
    "sleep_session_count": 7,
}


def _phase(phases, slug):
    return next(item for item in phases if item["phase"] == slug)


def _hhmm(iso_value):
    return iso_value[11:16]


class DayPhasesTests(unittest.TestCase):
    def test_wake_7_dip_and_melatonin_windows(self):
        phases = day_phases(WAKE_7, anchor=ANCHOR_BED_2330)
        dip = _phase(phases, "afternoon-dip")
        self.assertEqual(_hhmm(dip["start_iso"]), "13:00")
        self.assertEqual(_hhmm(dip["end_iso"]), "15:00")
        melatonin = _phase(phases, "melatonin-window")
        self.assertEqual(_hhmm(melatonin["start_iso"]), "22:30")
        self.assertEqual(_hhmm(melatonin["end_iso"]), "23:00")
        wind_down = _phase(phases, "wind-down")
        self.assertEqual(_hhmm(wind_down["start_iso"]), "21:30")
        self.assertEqual(_hhmm(wind_down["end_iso"]), "23:30")
        grog = _phase(phases, "grogginess")
        self.assertEqual(_hhmm(grog["start_iso"]), "07:00")

    def test_wake_9_shifts_dip_and_melatonin(self):
        phases = day_phases(WAKE_9)  # no anchor -> bedtime = wake + 16.5h = 01:30
        dip = _phase(phases, "afternoon-dip")
        self.assertEqual(_hhmm(dip["start_iso"]), "15:00")
        self.assertEqual(_hhmm(dip["end_iso"]), "17:00")
        melatonin = _phase(phases, "melatonin-window")
        self.assertEqual(_hhmm(melatonin["start_iso"]), "00:30")
        self.assertEqual(_hhmm(melatonin["end_iso"]), "01:00")
        self.assertEqual(melatonin["start_iso"][:10], "2026-06-11")

    def test_light_shift_moves_dip_not_grogginess(self):
        base = day_phases(WAKE_7, anchor=ANCHOR_BED_2330)
        shifted = day_phases(WAKE_7, anchor=ANCHOR_BED_2330, light_shift_minutes=30)
        self.assertEqual(_hhmm(_phase(shifted, "afternoon-dip")["start_iso"]), "13:30")
        self.assertEqual(
            _phase(base, "grogginess")["start_iso"],
            _phase(shifted, "grogginess")["start_iso"],
        )
        # Bed-anchored windows do not move with morning light.
        self.assertEqual(
            _phase(base, "melatonin-window")["start_iso"],
            _phase(shifted, "melatonin-window")["start_iso"],
        )

    def test_labels_advice_confidence_present(self):
        phases = day_phases(WAKE_7, anchor=ANCHOR_BED_2330)
        self.assertEqual(len(phases), len(ENERGY_PHASE_INFO))
        for item in phases:
            self.assertTrue(item["label_ru"].strip())
            self.assertTrue(item["advice_ru"].strip())
            self.assertIn(item["confidence"], {"C2", "C3", "C4"})


class EnergyCurveTests(unittest.TestCase):
    def test_curve_is_continuous_and_bounded(self):
        curve = energy_curve(WAKE_7, sleep_debt_h=0.0, points_per_hour=4, anchor=ANCHOR_BED_2330)
        self.assertEqual(len(curve), 24 * 4)
        energies = [point["energy"] for point in curve]
        self.assertTrue(all(0.0 <= value <= 100.0 for value in energies))
        max_step = max(abs(b - a) for a, b in zip(energies, energies[1:]))
        self.assertLessEqual(max_step, 10.0)
        self.assertEqual(curve[0]["phase"], "grogginess")
        self.assertTrue(curve[0]["t_iso"].startswith("2026-06-10T07:00"))

    def test_debt_deepens_afternoon_dip(self):
        def dip_min(debt_h):
            curve = energy_curve(WAKE_7, sleep_debt_h=debt_h, anchor=ANCHOR_BED_2330)
            window = [
                point["energy"]
                for point in curve
                if "13:00" <= _hhmm(point["t_iso"]) < "15:30"
            ]
            return min(window)

        self.assertLess(dip_min(6.0), dip_min(0.0) - 5.0)

    def test_debt_trims_morning_peak(self):
        def peak_max(debt_h):
            curve = energy_curve(WAKE_7, sleep_debt_h=debt_h, anchor=ANCHOR_BED_2330)
            return max(point["energy"] for point in curve)

        self.assertLess(peak_max(8.0), peak_max(0.0))

    def test_phases_cover_known_points(self):
        curve = energy_curve(WAKE_7, anchor=ANCHOR_BED_2330)
        by_time = {_hhmm(point["t_iso"]): point["phase"] for point in curve}
        self.assertEqual(by_time["14:00"], "afternoon-dip")
        self.assertEqual(by_time["10:00"], "morning-peak")
        self.assertEqual(by_time["22:45"], "melatonin-window")
        self.assertEqual(by_time["21:45"], "wind-down")


class EnergyScheduleTests(unittest.TestCase):
    def test_schedule_bundles_consistent_sources(self):
        schedule = energy_schedule(WAKE_7, anchor=ANCHOR_BED_2330, sleep_debt_h=2.0)
        self.assertEqual(schedule["model"], "two-process-rise@v1")
        self.assertEqual(schedule["wake_time"], WAKE_7.isoformat())
        self.assertEqual(_hhmm(schedule["bed_time"]), "23:30")
        self.assertEqual(len(schedule["curve"]), 96)
        melatonin = _phase(schedule["phases"], "melatonin-window")
        self.assertEqual(schedule["melatonin_window"]["start_iso"], melatonin["start_iso"])
        self.assertEqual(schedule["melatonin_window"]["end_iso"], melatonin["end_iso"])
        self.assertEqual(schedule["personal_fit"], "C2")
        self.assertTrue(schedule["evidence_note"].strip())

    def test_unusable_anchor_falls_back_to_default_day_length(self):
        # A bedtime before wake (corrupt anchor) must not produce a negative day.
        bad_anchor = dict(ANCHOR_BED_2330, bed_minutes=5 * 60)
        schedule = energy_schedule(WAKE_7, anchor=bad_anchor)
        bed = datetime.fromisoformat(schedule["bed_time"])
        self.assertEqual(bed - WAKE_7, timedelta(hours=16, minutes=30))

    def test_wake_time_accepts_hhmm_string(self):
        schedule = energy_schedule("07:00", anchor=ANCHOR_BED_2330)
        self.assertEqual(_hhmm(schedule["wake_time"]), "07:00")


if __name__ == "__main__":
    unittest.main()
