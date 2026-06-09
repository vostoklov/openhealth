import math
import tempfile
import unittest
from pathlib import Path

from openhealth import index, modules
from openhealth.modules import recovery


class RecoveryComponentTests(unittest.TestCase):
    def test_hrv_component_baseline_is_midpoint(self):
        # ln(50) - ln(50) = 0 -> exactly the midpoint regardless of ln-SD.
        self.assertAlmostEqual(recovery.hrv_component(50.0, 50.0), 50.0, places=6)

    def test_hrv_component_above_baseline_rises_in_ln_sd(self):
        # +1 SD above baseline in ln-space, full swing = 2 SD -> 50 + 50*(1/2) = 75.
        ln_sd = 0.1
        hrv = 50.0 * math.exp(ln_sd)  # exactly +1 ln-SD
        self.assertAlmostEqual(
            recovery.hrv_component(hrv, 50.0, baseline_ln_sd=ln_sd),
            50.0 + 50.0 * (1.0 / recovery._HRV_FULL_SWING_SD),
            places=4,
        )

    def test_hrv_component_below_baseline_falls(self):
        ln_sd = 0.1
        hrv = 50.0 * math.exp(-ln_sd)  # -1 ln-SD
        self.assertAlmostEqual(
            recovery.hrv_component(hrv, 50.0, baseline_ln_sd=ln_sd),
            50.0 - 50.0 * (1.0 / recovery._HRV_FULL_SWING_SD),
            places=4,
        )

    def test_hrv_component_clamped_0_100(self):
        # Far above / below baseline saturates at the 2-SD edges.
        ln_sd = 0.1
        self.assertEqual(recovery.hrv_component(50.0 * math.exp(5 * ln_sd), 50.0, baseline_ln_sd=ln_sd), 100.0)
        self.assertEqual(recovery.hrv_component(50.0 * math.exp(-5 * ln_sd), 50.0, baseline_ln_sd=ln_sd), 0.0)

    def test_hrv_component_uses_default_ln_sd_when_missing(self):
        # Without a personal ln-SD it falls back to the conservative default.
        hrv = 50.0 * math.exp(recovery._HRV_DEFAULT_LN_SD)  # +1 default-SD
        self.assertAlmostEqual(
            recovery.hrv_component(hrv, 50.0),
            50.0 + 50.0 * (1.0 / recovery._HRV_FULL_SWING_SD),
            places=4,
        )

    def test_hrv_component_rejects_nonpositive(self):
        with self.assertRaises(ValueError):
            recovery.hrv_component(0.0, 50.0)
        with self.assertRaises(ValueError):
            recovery.hrv_component(50.0, 0.0)

    def test_rhr_component_inverted(self):
        # Lower RHR than baseline => above 50 (better recovery).
        self.assertGreater(recovery.rhr_component(45.0, 55.0), 50.0)
        self.assertLess(recovery.rhr_component(65.0, 55.0), 50.0)
        self.assertAlmostEqual(recovery.rhr_component(55.0, 55.0), 50.0, places=6)

    def test_respiratory_component_full_at_baseline(self):
        self.assertEqual(recovery.respiratory_component(16.0, 16.0), 100.0)

    def test_respiratory_component_deadband_then_penalty(self):
        # Within the deadband (1.0 br/min) -> still full.
        self.assertEqual(recovery.respiratory_component(16.8, 16.0), 100.0)
        # 2.0 above baseline = 1.0 past the deadband, full swing 3.0 -> ~66.7.
        self.assertAlmostEqual(
            recovery.respiratory_component(18.0, 16.0),
            100.0 - 100.0 * (1.0 / recovery._RESP_FULL_SWING),
            places=4,
        )
        # Deviation either direction penalizes symmetrically.
        self.assertAlmostEqual(
            recovery.respiratory_component(14.0, 16.0),
            recovery.respiratory_component(18.0, 16.0),
            places=6,
        )

    def test_respiratory_component_clamped(self):
        self.assertEqual(recovery.respiratory_component(30.0, 16.0), 0.0)

    def test_recovery_score_weighted_blend_with_respiratory(self):
        ln_sd = 0.1
        hrv = 50.0 * math.exp(ln_sd)  # +1 ln-SD
        out = recovery.recovery_score(
            hrv_ms=hrv, baseline_hrv_ms=50.0, baseline_hrv_ln_sd=ln_sd,
            rhr_bpm=50.0, baseline_rhr_bpm=55.0,
            sleep_performance_pct=80.0,
            respiratory_rate=16.0, baseline_respiratory_rate=16.0,
        )
        hrv_c = 50.0 + 50.0 * (1.0 / recovery._HRV_FULL_SWING_SD)
        rhr_c = 50.0 - 50.0 * ((50.0 / 55.0 - 1.0) / recovery._RHR_FULL_SWING)
        resp_c = 100.0
        w = recovery.RECOVERY_WEIGHTS
        total = w["hrv"] + w["rhr"] + w["respiratory"] + w["sleep"]
        expected = round(
            (hrv_c * w["hrv"] + rhr_c * w["rhr"] + resp_c * w["respiratory"] + 80.0 * w["sleep"]) / total,
            1,
        )
        self.assertEqual(out["score"], expected)
        self.assertEqual(set(out["components"]), {"hrv", "rhr", "respiratory", "sleep"})
        self.assertEqual(out["missing"], [])
        self.assertEqual(out["method"], "ln_rmssd_sd")

    def test_recovery_score_renormalizes_when_respiratory_absent(self):
        # No respiratory inputs -> weights renormalize over hrv/rhr/sleep only.
        out = recovery.recovery_score(
            hrv_ms=50.0, baseline_hrv_ms=50.0,
            rhr_bpm=55.0, baseline_rhr_bpm=55.0,
            sleep_performance_pct=70.0,
        )
        self.assertIn("respiratory", out["missing"])
        self.assertNotIn("respiratory", out["weights_used"])
        # Present weights renormalize to sum 1.0.
        self.assertAlmostEqual(sum(out["weights_used"].values()), 1.0, places=4)
        w = recovery.RECOVERY_WEIGHTS
        total = w["hrv"] + w["rhr"] + w["sleep"]
        self.assertAlmostEqual(out["weights_used"]["hrv"], w["hrv"] / total, places=4)

    def test_recovery_score_partial_renormalizes_hrv_only(self):
        out = recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0)
        self.assertEqual(out["score"], 50.0)
        self.assertEqual(out["weights_used"], {"hrv": 1.0})
        self.assertIn("rhr", out["missing"])
        self.assertIn("sleep", out["missing"])
        self.assertIn("respiratory", out["missing"])

    def test_recovery_score_requires_hrv(self):
        with self.assertRaises(ValueError):
            recovery.recovery_score(hrv_ms=None, baseline_hrv_ms=50.0)

    def test_recovery_score_flags_default_ln_sd(self):
        out = recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0)
        self.assertTrue(out["hrv_ln_sd_is_default"])
        self.assertEqual(out["hrv_ln_sd_used"], round(recovery._HRV_DEFAULT_LN_SD, 4))
        out2 = recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0, baseline_hrv_ln_sd=0.2)
        self.assertFalse(out2["hrv_ln_sd_is_default"])
        self.assertEqual(out2["hrv_ln_sd_used"], 0.2)

    def test_strain_clamped_to_0_21(self):
        self.assertEqual(recovery.normalize_strain(25.0)["strain"], 21.0)
        self.assertTrue(recovery.normalize_strain(25.0)["clamped"])
        self.assertEqual(recovery.normalize_strain(10.5)["strain"], 10.5)
        self.assertFalse(recovery.normalize_strain(10.5)["clamped"])

    def test_strain_carries_log_scale_note(self):
        self.assertIn("logarithmic", recovery.normalize_strain(10.0)["scale_note"])

    def test_sleep_debt_single_night(self):
        sd = recovery.sleep_debt(6.5, need_h=8.0)
        self.assertEqual(sd["sleep_debt_h"], 1.5)
        self.assertEqual(sd["surplus_h"], 0.0)
        self.assertNotIn("accumulated_debt_h", sd)
        sd2 = recovery.sleep_debt(9.0, need_h=8.0)
        self.assertEqual(sd2["sleep_debt_h"], 0.0)
        self.assertEqual(sd2["surplus_h"], 1.0)

    def test_sleep_debt_personal_need(self):
        sd = recovery.sleep_debt(7.0, need_h=7.5)
        self.assertEqual(sd["need_h"], 7.5)
        self.assertEqual(sd["sleep_debt_h"], 0.5)

    def test_sleep_debt_accumulates_over_window(self):
        # Five short nights: shortfalls 1+0.5+0+2+1 = 4.5 against need 8.0.
        nights = [7.0, 7.5, 8.5, 6.0, 7.0]
        sd = recovery.sleep_debt(7.0, need_h=8.0, recent_nights_h=nights, window_nights=14)
        self.assertEqual(sd["accumulated_debt_h"], 4.5)
        self.assertEqual(sd["debt_window_nights"], 5)
        self.assertEqual(sd["debt_window_target_nights"], 14)

    def test_sleep_debt_window_truncates_to_recent_nights(self):
        # Only the trailing `window_nights` nights count toward accumulated debt.
        nights = [4.0, 4.0, 8.0, 8.0, 8.0]  # first two short are outside a 3-night window
        sd = recovery.sleep_debt(8.0, need_h=8.0, recent_nights_h=nights, window_nights=3)
        self.assertEqual(sd["accumulated_debt_h"], 0.0)
        self.assertEqual(sd["debt_window_nights"], 3)


class RecoveryVersioningTests(unittest.TestCase):
    """Every metric must carry an algo_version for reproducibility."""

    def test_versions_present_on_each_score(self):
        self.assertEqual(
            recovery.recovery_score(hrv_ms=50.0, baseline_hrv_ms=50.0)["algo_version"],
            "recovery_score@v3",
        )
        self.assertEqual(recovery.normalize_strain(10.0)["algo_version"], "strain@v1")
        self.assertEqual(recovery.sleep_debt(7.0)["algo_version"], "sleep_debt@v2")

    def test_module_metrics_carry_versions(self):
        modules.load_builtin()
        m = modules.get_module("recovery")
        res = m.compute({
            "date": "2026-06-01",
            "hrv_ms": 55.0, "baseline_hrv_ms": 50.0, "baseline_hrv_ln_sd": 0.12,
            "rhr_bpm": 52.0, "baseline_rhr_bpm": 55.0,
            "respiratory_rate": 16.0, "baseline_respiratory_rate": 16.0,
            "sleep_performance_pct": 75.0,
            "strain": 11.0,
            "actual_sleep_h": 7.0,
        })
        kinds = {mm["observation_kind"] for mm in res.metrics}
        self.assertEqual(kinds, {"recovery_score", "strain", "sleep_debt"})
        for mm in res.metrics:
            self.assertIn("algo_version", mm["metadata"])
        score_meta = next(mm["metadata"] for mm in res.metrics if mm["observation_kind"] == "recovery_score")
        self.assertIn("respiratory", score_meta["components"])


class RecoveryModuleTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_module_registered(self):
        m = modules.get_module("recovery")
        self.assertEqual(m.domain, "recovery")
        self.assertIn("hrv_ms", m.schema()["properties"])
        self.assertIn("respiratory_rate", m.schema()["properties"])

    def test_default_baseline_window_is_28(self):
        self.assertEqual(recovery.DEFAULT_BASELINE_WINDOW_DAYS, 28)

    def test_from_index_reads_whoop_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            for day, hrv, rhr in [
                ("2026-05-25", 48, 56),
                ("2026-05-28", 50, 55),
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
            payload = recovery.from_index(db, "2026-06-01", baseline_window_days=28)
            self.assertEqual(payload["hrv_ms"], 60.0)
            # baseline is the geometric mean of ln(rMSSD) within the window.
            expected_baseline = math.exp((math.log(48) + math.log(50) + math.log(60)) / 3.0)
            self.assertAlmostEqual(payload["baseline_hrv_ms"], expected_baseline, places=6)
            self.assertIsNotNone(payload["baseline_hrv_ln_sd"])
            # And the score computes cleanly from the assembled payload.
            m = modules.get_module("recovery")
            res = m.compute(payload)
            self.assertEqual(res.metrics[0]["metric_name"], "recovery_score")

    def test_from_index_window_excludes_old_records(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            # One in-window day and one far-older day; a 28d window drops the old one.
            for day, hrv in [("2026-03-01", 40), ("2026-06-01", 60)]:
                index.upsert_record(db, {
                    "id": f"whoop-recovery-{day}-hrv-rmssd",
                    "record_type": "Observation", "source_id": "whoop",
                    "title": "h", "summary": "s", "artifact_ids": [],
                    "evidence_class": "personal", "confidence": 0.96, "date": day,
                    "observation_kind": "whoop_recovery_metric", "metric_name": "hrv_rmssd",
                    "value": hrv, "unit": "ms",
                })
            p28 = recovery.from_index(db, "2026-06-01", baseline_window_days=28)
            self.assertAlmostEqual(p28["baseline_hrv_ms"], 60.0, places=6)  # only the recent day
            p120 = recovery.from_index(db, "2026-06-01", baseline_window_days=120)
            self.assertAlmostEqual(
                p120["baseline_hrv_ms"], math.exp((math.log(40) + math.log(60)) / 2.0), places=6
            )


if __name__ == "__main__":
    unittest.main()
