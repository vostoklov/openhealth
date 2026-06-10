import tempfile
import unittest
from pathlib import Path

from openhealth import index
from openhealth.modules import vo2max


class VO2MaxFormulaTests(unittest.TestCase):
    def test_uth_value_measured_hrmax(self):
        # 15.3 * 190 / 45 = 64.6
        out = vo2max.estimate_vo2max(hr_max=190.0, hr_rest=45.0)
        self.assertAlmostEqual(out["vo2max"], round(15.3 * 190.0 / 45.0, 1), places=6)
        self.assertEqual(out["hrmax_source"], "measured")
        self.assertEqual(out["confidence"], "C2")
        self.assertIn("Estimate only", out["disclaimer"])
        self.assertEqual(out["algo_version"], "vo2max@v1")

    def test_known_reference_value(self):
        # HRmax 200, HRrest 50 -> 15.3 * 4 = 61.2
        out = vo2max.estimate_vo2max(hr_max=200.0, hr_rest=50.0)
        self.assertAlmostEqual(out["vo2max"], 61.2, places=6)

    def test_age_fallback_when_no_measured_hrmax(self):
        # 220 - 30 = 190; 15.3 * 190 / 50 = 58.14
        out = vo2max.estimate_vo2max(hr_max=None, hr_rest=50.0, age=30.0)
        self.assertEqual(out["hr_max_used"], 190.0)
        self.assertEqual(out["hrmax_source"], "age_estimate_220_minus_age")
        self.assertAlmostEqual(out["vo2max"], round(15.3 * 190.0 / 50.0, 1), places=6)

    def test_measured_hrmax_preferred_over_age(self):
        out = vo2max.estimate_vo2max(hr_max=185.0, hr_rest=50.0, age=30.0)
        self.assertEqual(out["hr_max_used"], 185.0)
        self.assertEqual(out["hrmax_source"], "measured")

    def test_refuses_without_hrmax_or_age(self):
        with self.assertRaises(ValueError):
            vo2max.estimate_vo2max(hr_max=None, hr_rest=50.0)

    def test_refuses_without_hrrest(self):
        with self.assertRaises(ValueError):
            vo2max.estimate_vo2max(hr_max=190.0, hr_rest=None)
        with self.assertRaises(ValueError):
            vo2max.estimate_vo2max(hr_max=190.0, hr_rest=0.0)

    def test_always_c2(self):
        out = vo2max.estimate_vo2max(hr_max=190.0, hr_rest=45.0, age=35.0, sex="male")
        self.assertEqual(out["confidence"], "C2")

    def test_category_only_with_sex_and_age(self):
        bare = vo2max.estimate_vo2max(hr_max=190.0, hr_rest=45.0)
        self.assertNotIn("category", bare)
        with_cat = vo2max.estimate_vo2max(hr_max=190.0, hr_rest=45.0, age=35.0, sex="male")
        # ~64.6 ml/kg/min for a 35yo male -> excellent.
        self.assertEqual(with_cat["category"], "excellent")

    def test_category_low_value(self):
        # HRmax 160, HRrest 70 -> 15.3 * 160/70 ~ 34.97 ; 45yo male -> poor.
        out = vo2max.estimate_vo2max(hr_max=160.0, hr_rest=70.0, age=45.0, sex="male")
        self.assertEqual(out["category"], "poor")

    def test_plausible_range_flag(self):
        # Extreme inputs push the estimate out of the plausible band.
        out = vo2max.estimate_vo2max(hr_max=200.0, hr_rest=30.0)  # 102 -> implausible
        self.assertFalse(out["plausible_range"])


class VO2MaxModuleTests(unittest.TestCase):
    def test_not_self_registered_into_builtins_list(self):
        # The module self-registers on import (like pulse), but is intentionally
        # NOT wired into modules.load_builtin() yet — registration is a separate
        # decision. Importing the module triggers register(); confirm it lands.
        from openhealth.modules import base
        self.assertIn("vo2max", base._REGISTRY)
        m = base.get_module("vo2max")
        self.assertEqual(m.domain, "pulse")

    def test_compute_produces_metric(self):
        from openhealth.modules import base
        m = base.get_module("vo2max")
        res = m.compute({"date": "2026-03-14", "hr_max": 190.0, "hr_rest": 45.0})
        self.assertEqual(len(res.metrics), 1)
        metric = res.metrics[0]
        self.assertEqual(metric["metric_name"], "vo2max")
        self.assertEqual(metric["observation_kind"], "vo2max")
        self.assertAlmostEqual(metric["value"], round(15.3 * 190.0 / 45.0, 1), places=6)
        # C2 numeric confidence and a disclaimer in the summary.
        self.assertLessEqual(metric["confidence"], 0.35)
        self.assertIn("Estimate only", metric["summary"])

    def test_from_index_reads_hrmax_and_rhr(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            index.upsert_record(db, {
                "id": "whoop-body-max-heart-rate",
                "record_type": "Observation", "source_id": "whoop",
                "title": "h", "summary": "s", "artifact_ids": [],
                "evidence_class": "personal", "confidence": 0.95, "date": "2026-03-14",
                "observation_kind": "whoop_body_measurement", "metric_name": "max_heart_rate",
                "value": 190, "unit": "bpm",
            })
            index.upsert_record(db, {
                "id": "whoop-recovery-rhr",
                "record_type": "Observation", "source_id": "whoop",
                "title": "h", "summary": "s", "artifact_ids": [],
                "evidence_class": "personal", "confidence": 0.96, "date": "2026-03-14",
                "observation_kind": "whoop_recovery_metric", "metric_name": "resting_heart_rate",
                "value": 45, "unit": "bpm",
            })
            payload = vo2max.from_index(db, "2026-03-14")
            self.assertEqual(payload["hr_max"], 190.0)
            self.assertEqual(payload["hr_rest"], 45.0)
            out = vo2max.estimate_vo2max(payload["hr_max"], payload["hr_rest"])
            self.assertAlmostEqual(out["vo2max"], round(15.3 * 190.0 / 45.0, 1), places=6)


if __name__ == "__main__":
    unittest.main()
