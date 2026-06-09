import tempfile
import unittest
from pathlib import Path

from openhealth import index, modules
from openhealth.modules import recovery


class RecoveryComponentTests(unittest.TestCase):
    def test_hrv_component_baseline_is_midpoint(self):
        self.assertAlmostEqual(recovery.hrv_component(50.0, 50.0), 50.0, places=6)

    def test_hrv_component_above_baseline_rises(self):
        # +20% of a +/-30% full swing -> 50 + 50*(0.2/0.3) = 83.33
        self.assertAlmostEqual(recovery.hrv_component(60.0, 50.0), 50.0 + 50.0 * (0.2 / 0.3), places=4)

    def test_hrv_component_clamped_0_100(self):
        self.assertEqual(recovery.hrv_component(200.0, 50.0), 100.0)
        self.assertEqual(recovery.hrv_component(1.0, 50.0), 0.0)

    def test_rhr_component_inverted(self):
        # Lower RHR than baseline => above 50 (better recovery).
        self.assertGreater(recovery.rhr_component(45.0, 55.0), 50.0)
        self.assertLess(recovery.rhr_component(65.0, 55.0), 50.0)
        self.assertAlmostEqual(recovery.rhr_component(55.0, 55.0), 50.0, places=6)

    def test_recovery_score_weighted_blend(self):
        out = recovery.recovery_score(
            hrv_ms=60.0, baseline_hrv_ms=50.0,
            rhr_bpm=50.0, baseline_rhr_bpm=55.0,
            sleep_performance_pct=80.0,
        )
        # hrv=83.333, rhr=65.151..., sleep=80 ; weights .7/.2/.1
        hrv_c = 50.0 + 50.0 * (0.2 / 0.3)
        rhr_c = 50.0 - 50.0 * ((50.0 / 55.0 - 1.0) / 0.3)
        expected = round(hrv_c * 0.7 + rhr_c * 0.2 + 80.0 * 0.1, 1)
        self.assertEqual(out["score"], expected)
        self.assertEqual(set(out["components"]), {"hrv", "rhr", "sleep"})
        self.assertEqual(out["missing"], [])

    def test_recovery_score_partial_renormalizes(self):
        # Only HRV present -> weight renormalizes to 1.0, score == hrv component.
        out = recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0)
        self.assertEqual(out["score"], 50.0)
        self.assertEqual(out["weights_used"], {"hrv": 1.0})
        self.assertIn("rhr", out["missing"])
        self.assertIn("sleep", out["missing"])

    def test_recovery_score_requires_hrv(self):
        with self.assertRaises(ValueError):
            recovery.recovery_score(hrv_ms=None, baseline_hrv_ms=50.0)

    def test_strain_clamped_to_0_21(self):
        self.assertEqual(recovery.normalize_strain(25.0)["strain"], 21.0)
        self.assertTrue(recovery.normalize_strain(25.0)["clamped"])
        self.assertEqual(recovery.normalize_strain(10.5)["strain"], 10.5)
        self.assertFalse(recovery.normalize_strain(10.5)["clamped"])

    def test_sleep_debt(self):
        sd = recovery.sleep_debt(6.5, need_h=8.0)
        self.assertEqual(sd["sleep_debt_h"], 1.5)
        self.assertEqual(sd["surplus_h"], 0.0)
        sd2 = recovery.sleep_debt(9.0, need_h=8.0)
        self.assertEqual(sd2["sleep_debt_h"], 0.0)
        self.assertEqual(sd2["surplus_h"], 1.0)


class RecoveryVersioningTests(unittest.TestCase):
    """Every metric must carry an algo_version for reproducibility."""

    def test_versions_present_on_each_score(self):
        self.assertEqual(
            recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0)["algo_version"],
            "recovery_score@v1",
        )
        self.assertEqual(recovery.normalize_strain(10.0)["algo_version"], "strain@v1")
        self.assertEqual(recovery.sleep_debt(7.0)["algo_version"], "sleep_debt@v1")

    def test_module_metrics_carry_versions(self):
        modules.load_builtin()
        m = modules.get_module("recovery")
        res = m.compute({
            "date": "2026-06-01",
            "hrv_ms": 55.0, "baseline_hrv_ms": 50.0,
            "rhr_bpm": 52.0, "baseline_rhr_bpm": 55.0,
            "sleep_performance_pct": 75.0,
            "strain": 11.0,
            "actual_sleep_h": 7.0,
        })
        kinds = {mm["observation_kind"] for mm in res.metrics}
        self.assertEqual(kinds, {"recovery_score", "strain", "sleep_debt"})
        for mm in res.metrics:
            self.assertIn("algo_version", mm["metadata"])


class RecoveryModuleTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_module_registered(self):
        m = modules.get_module("recovery")
        self.assertEqual(m.domain, "recovery")
        self.assertIn("hrv_ms", m.schema()["properties"])

    def test_from_index_reads_whoop_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            # Seed a small WHOOP-shaped recovery + sleep set across days.
            for day, hrv, rhr in [
                ("2026-05-20", 48, 56),
                ("2026-05-21", 50, 55),
                ("2026-06-01", 60, 50),
            ]:
                index.upsert_record(db, {
                    "id": f"whoop-recovery-{day}-hrv-rmssd",
                    "record_type": "Observation", "source_id": "whoop",
                    "title": "h", "summary": "s", "artifact_ids": [],
                    "evidence_class": "personal", "confidence": 0.96, "date": day,
                    "observation_kind": "whoop_recovery_metric", "metric_name": "hrv_rmssd",
                    "value": hrv, "unit": "ms",
                })
                index.upsert_record(db, {
                    "id": f"whoop-recovery-{day}-rhr",
                    "record_type": "Observation", "source_id": "whoop",
                    "title": "h", "summary": "s", "artifact_ids": [],
                    "evidence_class": "personal", "confidence": 0.96, "date": day,
                    "observation_kind": "whoop_recovery_metric", "metric_name": "resting_heart_rate",
                    "value": rhr, "unit": "bpm",
                })
            payload = recovery.from_index(db, "2026-06-01", baseline_window_days=60)
            self.assertEqual(payload["hrv_ms"], 60.0)
            # baseline = mean of 48,50,60 within the window
            self.assertAlmostEqual(payload["baseline_hrv_ms"], (48 + 50 + 60) / 3.0, places=6)
            # And the score computes cleanly from the assembled payload.
            m = modules.get_module("recovery")
            res = m.compute(payload)
            self.assertEqual(res.metrics[0]["metric_name"], "recovery_score")


if __name__ == "__main__":
    unittest.main()
