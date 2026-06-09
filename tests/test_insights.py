"""Tests for openhealth.insights — detectors over synthetic daily series.

No network, no DB. Each detector gets a positive and a negative case plus a
threshold boundary; empty/garbage input must yield an empty list, not raise.
"""

import unittest
from datetime import date, timedelta

from openhealth import evidence, insights


def _days(start, n):
    d = date.fromisoformat(start)
    return [(d + timedelta(days=i)).isoformat() for i in range(n)]


def _daily(start, values_by_key):
    """Build {date: {key: value}} from {key: [values...]} of equal length."""
    n = max(len(v) for v in values_by_key.values())
    dates = _days(start, n)
    out = {}
    for i, dt in enumerate(dates):
        row = {}
        for key, vals in values_by_key.items():
            if i < len(vals) and vals[i] is not None:
                row[key] = vals[i]
        out[dt] = row
    return out


class SleepDebtTests(unittest.TestCase):
    def test_warning_on_large_debt(self):
        daily = _daily("2026-04-01", {"sleep_h": [6.5] * 7})  # 1.5h x7 = 10.5h
        ins = insights.detect_sleep_debt(daily, {"sleep_h": 8.0})
        self.assertIsNotNone(ins)
        self.assertEqual(ins.severity, insights.WARNING)
        self.assertIn(insights.WARNING_DISCLAIMER, ins.action_ru)

    def test_attention_band(self):
        daily = _daily("2026-04-01", {"sleep_h": [7.2] * 7})  # 0.8h x7 = 5.6h
        ins = insights.detect_sleep_debt(daily, {"sleep_h": 8.0})
        self.assertEqual(ins.severity, insights.ATTENTION)

    def test_below_threshold_is_none(self):
        daily = _daily("2026-04-01", {"sleep_h": [7.3] * 7})  # 0.7h x7 = 4.9h < 5
        self.assertIsNone(insights.detect_sleep_debt(daily, {"sleep_h": 8.0}))

    def test_meets_goal_is_none(self):
        daily = _daily("2026-04-01", {"sleep_h": [8.2] * 7})
        self.assertIsNone(insights.detect_sleep_debt(daily, {}))

    def test_uses_custom_goal(self):
        daily = _daily("2026-04-01", {"sleep_h": [7.0] * 7})
        # goal 7.0 -> no debt; default 8.0 would have flagged it
        self.assertIsNone(insights.detect_sleep_debt(daily, {"sleep_h": 7.0}))


class HrvDowntrendTests(unittest.TestCase):
    def _series(self, recent_val):
        return _daily("2026-04-01", {"hrv": [100.0] * 21 + [recent_val] * 7})

    def test_warning_on_15pct_drop(self):
        ins = insights.detect_hrv_downtrend(self._series(85.0), {})
        self.assertEqual(ins.severity, insights.WARNING)
        self.assertEqual(ins.metric, "hrv")

    def test_attention_on_8pct_drop(self):
        ins = insights.detect_hrv_downtrend(self._series(92.0), {})
        self.assertEqual(ins.severity, insights.ATTENTION)

    def test_small_drop_is_none(self):
        self.assertIsNone(insights.detect_hrv_downtrend(self._series(93.0), {}))

    def test_flat_is_none(self):
        self.assertIsNone(insights.detect_hrv_downtrend(self._series(100.0), {}))

    def test_too_little_data_is_none(self):
        daily = _daily("2026-04-01", {"hrv": [90.0] * 6})
        self.assertIsNone(insights.detect_hrv_downtrend(daily, {}))


class RhrUptrendTests(unittest.TestCase):
    def _series(self, recent_val):
        return _daily("2026-04-01", {"rhr": [50.0] * 21 + [recent_val] * 7})

    def test_warning_on_6bpm(self):
        ins = insights.detect_rhr_uptrend(self._series(56.0), {})
        self.assertEqual(ins.severity, insights.WARNING)

    def test_attention_on_3bpm(self):
        ins = insights.detect_rhr_uptrend(self._series(53.0), {})
        self.assertEqual(ins.severity, insights.ATTENTION)

    def test_small_rise_is_none(self):
        self.assertIsNone(insights.detect_rhr_uptrend(self._series(52.0), {}))


class RedStreakTests(unittest.TestCase):
    def test_three_in_a_row_warns(self):
        daily = _daily("2026-04-01", {"recovery": [60, 60, 30, 28, 25, 60, 70]})
        ins = insights.detect_recovery_red_streak(daily, {})
        self.assertIsNotNone(ins)
        self.assertEqual(ins.severity, insights.WARNING)
        self.assertEqual(ins.data["streak_len"], 3)

    def test_scattered_reds_no_streak(self):
        daily = _daily("2026-04-01", {"recovery": [30, 60, 30, 60, 30, 60]})
        self.assertIsNone(insights.detect_recovery_red_streak(daily, {}))


class MismatchTests(unittest.TestCase):
    def _daily_with_hits(self, n_hits):
        rec = [70] * 14
        strain = [8.0] * 14
        for i in range(n_hits):
            rec[i] = 40
            strain[i] = 16.0
        return _daily("2026-04-01", {"recovery": rec, "strain": strain})

    def test_two_hits_attention(self):
        ins = insights.detect_strain_recovery_mismatch(self._daily_with_hits(2), {})
        self.assertEqual(ins.severity, insights.ATTENTION)

    def test_three_hits_warning(self):
        ins = insights.detect_strain_recovery_mismatch(self._daily_with_hits(3), {})
        self.assertEqual(ins.severity, insights.WARNING)

    def test_one_hit_is_none(self):
        self.assertIsNone(insights.detect_strain_recovery_mismatch(self._daily_with_hits(1), {}))


class WeekendPatternTests(unittest.TestCase):
    def test_weekend_dip(self):
        # 2026-04-06 is a Monday; 4 full weeks.
        daily = {}
        for dt in _days("2026-04-06", 28):
            wd = date.fromisoformat(dt).weekday()
            daily[dt] = {"recovery": 55 if wd >= 5 else 72}
        ins = insights.detect_weekend_pattern(daily, {})
        self.assertIsNotNone(ins)
        self.assertEqual(ins.severity, insights.ATTENTION)
        self.assertTrue(ins.data["dip"])
        self.assertLessEqual(ins.confidence, evidence.Confidence.C2)

    def test_no_gap_is_none(self):
        daily = {}
        for dt in _days("2026-04-06", 28):
            daily[dt] = {"recovery": 70}
        self.assertIsNone(insights.detect_weekend_pattern(daily, {}))


class SleepConsistencyTests(unittest.TestCase):
    def test_high_variance_flags(self):
        daily = _daily("2026-04-01", {"sleep_h": [5.0, 8.0] * 7})  # pstdev 1.5
        ins = insights.detect_sleep_consistency(daily, {})
        self.assertIsNotNone(ins)
        self.assertEqual(ins.severity, insights.ATTENTION)

    def test_steady_sleep_is_none(self):
        daily = _daily("2026-04-01", {"sleep_h": [7.0, 7.4] * 7})  # pstdev 0.2
        self.assertIsNone(insights.detect_sleep_consistency(daily, {}))


class DetectInsightsTests(unittest.TestCase):
    def test_empty_input(self):
        self.assertEqual(insights.detect_insights({}), [])
        self.assertEqual(insights.detect_insights(None), [])

    def test_garbage_values_do_not_raise(self):
        daily = {"2026-04-01": {"hrv": "bad", "recovery": None}, "not-a-date": {"recovery": 50}}
        # Should simply find nothing rather than throwing.
        self.assertIsInstance(insights.detect_insights(daily), list)

    def test_sorted_warning_first(self):
        # sleep debt (warning) + weekend dip (attention) in one set.
        daily = {}
        for dt in _days("2026-04-06", 28):
            wd = date.fromisoformat(dt).weekday()
            daily[dt] = {"recovery": 55 if wd >= 5 else 72, "sleep_h": 6.3}
        out = insights.detect_insights(daily, {"sleep_h": 8.0})
        sev = [i.severity for i in out]
        self.assertIn(insights.WARNING, sev)
        # warning(s) come before attention/info
        self.assertEqual(sev, sorted(sev, key=lambda s: insights._SEVERITY_RANK[s]))

    def test_personal_patterns_capped_at_c2(self):
        daily = _daily("2026-04-01", {"hrv": [100.0] * 21 + [80.0] * 7})
        out = insights.detect_insights(daily, {})
        for ins in out:
            self.assertLessEqual(ins.confidence, evidence.Confidence.C2)

    def test_to_dict_shape(self):
        daily = _daily("2026-04-01", {"sleep_h": [6.5] * 7})
        d = insights.detect_insights(daily, {"sleep_h": 8.0})[0].to_dict()
        for key in ("id", "title_ru", "severity", "confidence", "confidence_label",
                    "evidence_text", "question_ru", "action_ru", "metric", "data", "refs"):
            self.assertIn(key, d)


if __name__ == "__main__":
    unittest.main()
