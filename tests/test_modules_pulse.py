import math
import unittest

from openhealth import modules
from openhealth.modules import pulse


class HRVTimeDomainGoldenTests(unittest.TestCase):
    """Exact golden values for hand-computable fixtures."""

    def test_flat_signal(self):
        rr = [800.0, 800.0, 800.0, 800.0]
        self.assertEqual(pulse.sdnn(rr), 0.0)
        self.assertEqual(pulse.rmssd(rr), 0.0)
        self.assertEqual(pulse.pnn50(rr), 0.0)
        self.assertAlmostEqual(pulse.mean_hr_bpm(rr), 75.0, places=6)

    def test_alternating_signal(self):
        rr = [800.0, 900.0, 800.0, 900.0]
        # diffs = [100, -100, 100] -> RMSSD = sqrt(30000/3) = 100
        self.assertAlmostEqual(pulse.rmssd(rr), 100.0, places=6)
        # all |diffs| > 50 -> 100%
        self.assertAlmostEqual(pulse.pnn50(rr), 100.0, places=6)
        # sample SD of [800,900,800,900], mean 850, dev^2 sum = 10000, /3
        self.assertAlmostEqual(pulse.sdnn(rr), math.sqrt(10000.0 / 3.0), places=6)
        self.assertAlmostEqual(pulse.mean_hr_bpm(rr), 60000.0 / 850.0, places=6)

    def test_cleaning_drops_artifacts(self):
        rr = [800, 0, -5, 5000, "x", 820]  # only 800 and 820 are plausible
        cleaned = pulse._clean_rr(rr)
        self.assertEqual(cleaned, [800.0, 820.0])

    def test_summary_requires_two_beats(self):
        with self.assertRaises(ValueError):
            pulse.hrv_summary([800])


class HRVFreqDomainSanityTests(unittest.TestCase):
    def test_freq_domain_positive_and_finite(self):
        # ~60s of beats around 60 bpm with a slow oscillation
        rr = []
        for i in range(60):
            rr.append(1000.0 + 40.0 * math.sin(2 * math.pi * 0.1 * i))
        fd = pulse.freq_domain(rr)
        self.assertGreater(fd["total_power"], 0.0)
        self.assertGreaterEqual(fd["lf"], 0.0)
        self.assertGreaterEqual(fd["hf"], 0.0)
        self.assertTrue(math.isfinite(fd["lf_hf"]))


class PulseModuleTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_module_registered(self):
        m = modules.get_module("pulse")
        self.assertEqual(m.domain, "pulse")
        self.assertIn("rr_intervals_ms", m.schema()["properties"])

    def test_compute_produces_metric(self):
        m = modules.get_module("pulse")
        res = m.compute({"date": "2024-06-01", "rr_intervals_ms": [800, 900, 800, 900]})
        self.assertEqual(len(res.metrics), 1)
        self.assertEqual(res.metrics[0]["metric_name"], "rmssd_ms")
        self.assertAlmostEqual(res.metrics[0]["value"], 100.0, places=3)

    def test_readiness_insight_capped_and_framed(self):
        m = modules.get_module("pulse")
        res = m.compute({
            "date": "2024-06-01",
            "rr_intervals_ms": [800, 805, 802, 808, 801, 806],  # low RMSSD
            "baseline_rmssd_ms": 45.0,
        })
        self.assertEqual(len(res.insights), 1)
        ins = res.insights[0]
        # Personal single-day reading must be capped to a weak signal (C2) and
        # framed as a question.
        self.assertLessEqual(ins["confidence"], 0.35)
        self.assertIn("?", ins["summary"])
        # Readiness now uses the ln-rMSSD normal-range method, not a raw ratio.
        self.assertEqual(ins["metadata"]["method"], "ln_rmssd_sd")

    def test_readiness_normal_range_within_band(self):
        # RMSSD ~100 ms vs a 100 ms baseline => within +/-1 SD => "normal day".
        m = modules.get_module("pulse")
        res = m.compute({
            "date": "2024-06-02",
            "rr_intervals_ms": [800, 900, 800, 900],  # RMSSD = 100
            "baseline_rmssd_ms": 100.0,
        })
        ins = res.insights[0]
        self.assertGreaterEqual(ins["metadata"]["z_sd"], -1.0)
        self.assertIn("normal day", ins["statement"])

    def test_readiness_personal_ln_sd_widens_band(self):
        # A large personal ln-SD keeps a mild dip inside the normal range, where
        # a fixed 0.7/0.9 ratio would have flagged it.
        m = modules.get_module("pulse")
        res = m.compute({
            "date": "2024-06-03",
            "rr_intervals_ms": [800, 870, 800, 870],  # RMSSD = 70
            "baseline_rmssd_ms": 100.0,
            "baseline_ln_sd": 0.6,  # wide personal spread
        })
        ins = res.insights[0]
        self.assertFalse(ins["metadata"]["ln_sd_is_default"])
        self.assertEqual(ins["metadata"]["ln_sd_used"], 0.6)
        self.assertGreaterEqual(ins["metadata"]["z_sd"], -1.0)
        self.assertIn("normal day", ins["statement"])


if __name__ == "__main__":
    unittest.main()
