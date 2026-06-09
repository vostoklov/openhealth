"""Tests for openhealth.clinical_optima — optimal ranges vs lab reference ranges.

Run this file alone:
    PYTHONPATH=$PWD python3 tests/test_clinical_optima.py
"""

import unittest

from openhealth import clinical_optima as co
from openhealth import reference_ranges
from openhealth.evidence import Confidence


class OptimalTableTests(unittest.TestCase):
    def test_every_optimal_marker_exists_in_reference_table(self):
        # An optimal range is keyed by a reference-range slug so the same value
        # can be assessed against both without re-identifying the marker.
        for key in co.OPTIMAL_RANGES:
            self.assertIn(key, reference_ranges.MARKERS, "unknown slug: %s" % key)

    def test_every_optimal_range_is_evidence_graded(self):
        for key, opt in co.OPTIMAL_RANGES.items():
            self.assertIsInstance(opt.confidence, Confidence)
            self.assertTrue(opt.source, "missing source for %s" % key)
            self.assertTrue(opt.source_url, "missing source_url for %s" % key)
            self.assertIn(opt.direction, (co.DIRECTION_RANGE, co.DIRECTION_HIGHER, co.DIRECTION_LOWER))


class ClassifyOptimalTests(unittest.TestCase):
    def test_range_marker_both_tails(self):
        opt = co.OPTIMAL_RANGES["vitamin_d"]  # optimal band 40-60 ng/mL
        self.assertEqual(co.classify_optimal(opt, 50.0), co.OPTIMAL)
        self.assertEqual(co.classify_optimal(opt, 22.0), co.SUBOPTIMAL_LOW)
        self.assertEqual(co.classify_optimal(opt, 80.0), co.SUBOPTIMAL_HIGH)
        self.assertEqual(co.classify_optimal(opt, None), co.UNKNOWN)

    def test_lower_is_better_marker(self):
        opt = co.OPTIMAL_RANGES["ldl"]  # optimal <=100 mg/dL, lower is better
        self.assertEqual(co.classify_optimal(opt, 80.0), co.OPTIMAL)
        self.assertEqual(co.classify_optimal(opt, 150.0), co.SUBOPTIMAL_HIGH)
        # A lower-is-better marker can never be "below optimal".
        self.assertNotEqual(co.classify_optimal(opt, 40.0), co.SUBOPTIMAL_LOW)

    def test_higher_is_better_marker(self):
        opt = co.OPTIMAL_RANGES["hdl"]  # optimal >=60 mg/dL, higher is better
        self.assertEqual(co.classify_optimal(opt, 70.0), co.OPTIMAL)
        self.assertEqual(co.classify_optimal(opt, 45.0), co.SUBOPTIMAL_LOW)


class AssessOptimaDualStatusTests(unittest.TestCase):
    def test_value_returns_both_statuses(self):
        # Vitamin D 22: lab fallback low bound is 30, so reference flags "low";
        # optimal band is 40-60, so it is also below_optimal. Both must appear.
        r = co.assess_optima("Vitamin D (25-OH)", value=22.0)
        self.assertEqual(r["marker_key"], "vitamin_d")
        self.assertEqual(r["reference_status"], "low")
        self.assertEqual(r["optimal_status"], co.SUBOPTIMAL_LOW)
        self.assertEqual(r["reference_source"], "fallback")
        self.assertIsNotNone(r["optimal"])
        self.assertEqual(r["optimal"]["confidence"], "C3")
        # The disclaimer is always present and says "not a diagnosis".
        self.assertIn("not a diagnosis", r["disclaimer"])

    def test_normal_by_lab_but_below_optimal(self):
        # The whole point of this module: a value the lab calls NORMAL can still
        # be flagged below an optimal target. HbA1c 5.6% is < lab cut 5.7%
        # (normal) but above the optimal target 5.4% (above_optimal).
        r = co.assess_optima("HbA1c", value=5.6)
        self.assertEqual(r["reference_status"], "normal")
        self.assertEqual(r["optimal_status"], co.SUBOPTIMAL_HIGH)
        self.assertEqual(r["optimal"]["confidence"], "C4")

    def test_optimal_value_is_optimal_and_normal(self):
        # LDL 80: normal by lab (fallback high 100) and optimal (<=100).
        r = co.assess_optima("LDL", value=80.0)
        self.assertEqual(r["reference_status"], "normal")
        self.assertEqual(r["optimal_status"], co.OPTIMAL)
        self.assertIn("Not a diagnosis", r["summary"])

    def test_marker_without_optimal_range(self):
        # Creatinine has a reference range but no optimal target here. Reference
        # status still comes back; optimal_status is None, not invented.
        r = co.assess_optima("Creatinine", value=1.0)
        self.assertIsNotNone(r)
        self.assertEqual(r["reference_status"], "normal")
        self.assertIsNone(r["optimal_status"])
        self.assertIsNone(r["optimal"])
        self.assertIn("disclaimer", r)

    def test_unknown_marker_returns_none(self):
        self.assertIsNone(co.assess_optima("Unobtainium", value=1.0))


class SexSpecificOptimalTests(unittest.TestCase):
    def test_ferritin_sex_override(self):
        # Female optimal ceiling is tighter (122) than male (150).
        male = co.assess_optima("Ferritin", value=140.0, sex="male")
        self.assertEqual(male["optimal_status"], co.OPTIMAL)
        female = co.assess_optima("Ferritin", value=140.0, sex="female")
        self.assertEqual(female["optimal_status"], co.SUBOPTIMAL_HIGH)


class RedFlagShortCircuitTests(unittest.TestCase):
    def test_critical_glucose_routes_to_clinician(self):
        # Glucose 320 is in evidence.CRITICAL_LAB_THRESHOLDS (>=300). The
        # optimal interpretation must be suppressed and a red flag raised.
        r = co.assess_optima("Glucose", value=320.0)
        self.assertIsNotNone(r["red_flag"])
        self.assertEqual(r["red_flag"]["action"], "see-clinician")
        self.assertEqual(r["red_flag"]["urgency"], "urgent")
        # We do not offer an "optimal" reading of an emergency value.
        self.assertEqual(r["optimal_status"], co.UNKNOWN)
        self.assertIn("clinician", r["summary"].lower())

    def test_normal_glucose_has_no_red_flag(self):
        r = co.assess_optima("Glucose", value=82.0)
        self.assertIsNone(r["red_flag"])
        self.assertEqual(r["optimal_status"], co.OPTIMAL)  # 72-85 band


class PanelTests(unittest.TestCase):
    def test_mixed_panel_dual_and_raw(self):
        markers = [
            {"name": "LDL", "value": 160.0, "unit": "mg/dL"},
            {"name": "HDL", "value": 70.0, "unit": "mg/dL"},
            {"name": "Mystery Marker", "value": 42.0, "unit": "mg/dL"},
        ]
        out = co.assess_panel(markers, sex="male")
        self.assertEqual(len(out), 3)

        ldl = next(m for m in out if m["marker_key"] == "ldl")
        self.assertEqual(ldl["optimal_status"], co.SUBOPTIMAL_HIGH)

        hdl = next(m for m in out if m["marker_key"] == "hdl")
        self.assertEqual(hdl["optimal_status"], co.OPTIMAL)

        mystery = next(m for m in out if m.get("raw"))
        self.assertIsNone(mystery["marker_key"])
        self.assertEqual(mystery["value"], 42.0)

        # Every row carries the standing disclaimer.
        for row in out:
            self.assertIn("not a diagnosis", row["disclaimer"])


if __name__ == "__main__":
    unittest.main()
