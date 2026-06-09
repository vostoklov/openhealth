"""Tests for the Oura and Garmin export connectors.

All fixtures are synthetic. They model the public export shapes:
  * Oura  — wide "trends" CSV (durations in seconds) + API V2 JSON.
  * Garmin — Garmin Health API JSON (PascalCase) + Connect web CSV.

Run directly:  PYTHONPATH=$PWD python3 tests/test_connectors_oura_garmin.py
"""

import json
import os
import tempfile
import unittest

from openhealth.connectors import garmin, oura


def _by(records, metric, date=None):
    for r in records:
        if r["metric_name"] == metric and (date is None or r["date"] == date):
            return r
    return None


# --------------------------------------------------------------------------- #
# Oura fixtures
# --------------------------------------------------------------------------- #

# Wide trends CSV: prefixed scores so sleep/readiness/activity don't collide,
# durations in seconds, raw hr/hrv columns.
OURA_CSV = (
    "summary_date,sleep_score,readiness_score,activity_score,"
    "total,deep,rem,light,onset_latency,efficiency,hr_average,hr_lowest,rmssd,breath_average,steps,cal_active\n"
    "2024-06-01,82,71,90,28800,6480,5400,16920,900,94,52,48,65,14.2,9000,420\n"
    "2024-06-02,75,80,60,25200,5400,4500,15300,600,90,55,50,58,15.0,4000,300\n"
)

# API V2 JSON: nested by summary family, snake_case fields.
OURA_JSON = {
    "sleep": [
        {
            "summary_date": "2024-06-03",
            "score": 88,
            "total_sleep_duration": 27000,  # 7.5 h
            "deep_sleep_duration": 6000,
            "rem_sleep_duration": 5400,
            "average_heart_rate": 49,
            "lowest_heart_rate": 44,
            "average_hrv": 70,
            "average_breath": 13.5,
        }
    ],
    "readiness": [
        {"day": "2024-06-03", "score": 79, "resting_heart_rate": 45},
    ],
    "activity": [
        {"summary_date": "2024-06-03", "score": 91, "steps": 11000, "cal_active": 510},
    ],
}


# --------------------------------------------------------------------------- #
# Garmin fixtures
# --------------------------------------------------------------------------- #

# Garmin Health API style JSON: list of typed daily summaries, PascalCase keys.
GARMIN_JSON = [
    {
        "summaryType": "sleep",
        "CalendarDate": "2024-06-01",
        "DurationInSeconds": 27000,           # 7.5 h
        "DeepSleepDurationInSeconds": 6300,
        "RemSleepInSeconds": 5400,
        "LightSleepDurationInSeconds": 14400,
        "AwakeDurationInSeconds": 900,
        "OverallSleepScore": 84,
    },
    {
        "summaryType": "hrv",
        "CalendarDate": "2024-06-01",
        "LastNightAvg": 62,
        "LastNight5MinHigh": 95,
    },
    {
        "summaryType": "stress",
        "CalendarDate": "2024-06-01",
        "AverageStressLevel": 33,
        "BodyBatteryChargedValue": 88,
        "BodyBatteryDrainedValue": 21,
    },
    {
        "summaryType": "daily",
        "CalendarDate": "2024-06-01",
        "Steps": 9500,
        "RestingHeartRateInBeatsPerMinute": 47,
        "AverageHeartRateInBeatsPerMinute": 66,
        "ActiveKilocalories": 480,
        "AverageSpo2Value": 97,
        "DistanceInMeters": 7200,
    },
]

# Garmin Connect web CSV: human headers, h/m durations, one row per day.
GARMIN_CSV = (
    "Date,Total Sleep,Deep Sleep,REM Sleep,Resting Heart Rate,Avg Stress Level,Steps\n"
    "2024-06-02,7h 0m,1h 30m,1h 15m,50,40,4200\n"
    "2024-06-03,6:30,1:00,1:10,52,45,3100\n"
)


class OuraImportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.csv = os.path.join(self.dir, "oura.csv")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write(OURA_CSV)
        self.json = os.path.join(self.dir, "oura.json")
        with open(self.json, "w", encoding="utf-8") as f:
            json.dump(OURA_JSON, f)

    def test_csv_seconds_to_hours(self):
        recs = oura.import_oura(self.csv)
        self.assertEqual(_by(recs, "sleep_duration_h", "2024-06-01")["value"], 8.0)   # 28800s
        self.assertEqual(_by(recs, "sleep_deep_h", "2024-06-01")["value"], 1.8)        # 6480s
        self.assertEqual(_by(recs, "sleep_latency_min", "2024-06-01")["value"], 15.0)  # 900s

    def test_csv_scores_do_not_collide(self):
        recs = oura.import_oura(self.csv)
        self.assertEqual(_by(recs, "sleep_score", "2024-06-01")["value"], 82.0)
        self.assertEqual(_by(recs, "readiness_score", "2024-06-01")["value"], 71.0)
        self.assertEqual(_by(recs, "activity_score", "2024-06-01")["value"], 90.0)

    def test_csv_raw_pulse_signals(self):
        recs = oura.import_oura(self.csv)
        self.assertEqual(_by(recs, "hrv_rmssd_ms", "2024-06-01")["value"], 65.0)
        self.assertEqual(_by(recs, "resting_hr_bpm", "2024-06-01")["value"], 48.0)
        self.assertEqual(_by(recs, "heart_rate_avg_bpm", "2024-06-01")["value"], 52.0)

    def test_json_nested_families(self):
        recs = oura.import_oura(self.json)
        self.assertEqual(_by(recs, "sleep_duration_h", "2024-06-03")["value"], 7.5)
        self.assertEqual(_by(recs, "sleep_score", "2024-06-03")["value"], 88.0)
        self.assertEqual(_by(recs, "readiness_score", "2024-06-03")["value"], 79.0)
        self.assertEqual(_by(recs, "activity_score", "2024-06-03")["value"], 91.0)
        self.assertEqual(_by(recs, "hrv_rmssd_ms", "2024-06-03")["value"], 70.0)
        self.assertEqual(_by(recs, "steps", "2024-06-03")["value"], 11000.0)

    def test_observation_shape_and_source(self):
        recs = oura.import_oura(self.csv)
        rec = _by(recs, "hrv_rmssd_ms", "2024-06-01")
        self.assertEqual(rec["record_type"], "Observation")
        self.assertEqual(rec["source_id"], "oura")
        self.assertEqual(rec["metadata"]["source"], "oura")
        self.assertEqual(rec["evidence_class"], "personal")
        self.assertIn("oura", rec["tags"])
        self.assertIn("pulse", rec["tags"])
        self.assertTrue(rec["id"].startswith("obs-oura-"))

    def test_score_confidence_lower_than_raw(self):
        recs = oura.import_oura(self.csv)
        score = _by(recs, "sleep_score", "2024-06-01")
        raw = _by(recs, "hrv_rmssd_ms", "2024-06-01")
        self.assertLess(score["confidence"], raw["confidence"])

    def test_days_back_filters_old(self):
        # All fixture dates are in 2024 -> days_back=1 yields nothing.
        recs = oura.import_oura(self.csv, days_back=1)
        self.assertEqual(recs, [])

    def test_summarize(self):
        recs = oura.import_oura(self.csv)
        s = oura.summarize(recs)
        self.assertEqual(s["source"], "oura")
        self.assertEqual(s["date_from"], "2024-06-01")
        self.assertEqual(s["date_to"], "2024-06-02")
        self.assertIn("sleep_score", s["metrics"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            oura.import_oura(os.path.join(self.dir, "nope.csv"))


class GarminImportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.json = os.path.join(self.dir, "garmin.json")
        with open(self.json, "w", encoding="utf-8") as f:
            json.dump(GARMIN_JSON, f)
        self.csv = os.path.join(self.dir, "garmin.csv")
        with open(self.csv, "w", encoding="utf-8") as f:
            f.write(GARMIN_CSV)

    def test_json_sleep_seconds_to_hours(self):
        recs = garmin.import_garmin(self.json)
        self.assertEqual(_by(recs, "sleep_duration_h", "2024-06-01")["value"], 7.5)   # 27000s
        self.assertEqual(_by(recs, "sleep_deep_h", "2024-06-01")["value"], 1.75)       # 6300s
        self.assertEqual(_by(recs, "sleep_awake_h", "2024-06-01")["value"], 0.25)      # 900s

    def test_json_hrv_surfaced(self):
        recs = garmin.import_garmin(self.json)
        self.assertEqual(_by(recs, "hrv_rmssd_ms", "2024-06-01")["value"], 62.0)
        self.assertEqual(_by(recs, "hrv_5min_high_ms", "2024-06-01")["value"], 95.0)
        # HRV must be tagged pulse (the project's primary signal lives there).
        self.assertIn("pulse", _by(recs, "hrv_rmssd_ms", "2024-06-01")["tags"])

    def test_json_stress_and_body_battery(self):
        recs = garmin.import_garmin(self.json)
        self.assertEqual(_by(recs, "stress_avg", "2024-06-01")["value"], 33.0)
        self.assertEqual(_by(recs, "body_battery_high", "2024-06-01")["value"], 88.0)
        self.assertEqual(_by(recs, "body_battery_low", "2024-06-01")["value"], 21.0)

    def test_json_daily_metrics(self):
        recs = garmin.import_garmin(self.json)
        self.assertEqual(_by(recs, "steps", "2024-06-01")["value"], 9500.0)
        self.assertEqual(_by(recs, "resting_hr_bpm", "2024-06-01")["value"], 47.0)
        self.assertEqual(_by(recs, "spo2_pct", "2024-06-01")["value"], 97.0)

    def test_csv_hms_durations(self):
        recs = garmin.import_garmin(self.csv)
        self.assertEqual(_by(recs, "sleep_duration_h", "2024-06-02")["value"], 7.0)    # 7h 0m
        self.assertEqual(_by(recs, "sleep_deep_h", "2024-06-02")["value"], 1.5)        # 1h 30m
        self.assertEqual(_by(recs, "sleep_duration_h", "2024-06-03")["value"], 6.5)    # 6:30
        self.assertEqual(_by(recs, "sleep_rem_h", "2024-06-03")["value"], round(1 + 10 / 60.0, 2))  # 1:10

    def test_csv_daily_values(self):
        recs = garmin.import_garmin(self.csv)
        self.assertEqual(_by(recs, "resting_hr_bpm", "2024-06-02")["value"], 50.0)
        self.assertEqual(_by(recs, "stress_avg", "2024-06-02")["value"], 40.0)
        self.assertEqual(_by(recs, "steps", "2024-06-03")["value"], 3100.0)

    def test_observation_shape_and_source(self):
        recs = garmin.import_garmin(self.json)
        rec = _by(recs, "hrv_rmssd_ms", "2024-06-01")
        self.assertEqual(rec["record_type"], "Observation")
        self.assertEqual(rec["source_id"], "garmin")
        self.assertEqual(rec["metadata"]["source"], "garmin")
        self.assertEqual(rec["evidence_class"], "personal")
        self.assertIn("garmin", rec["tags"])
        self.assertTrue(rec["id"].startswith("obs-garmin-"))

    def test_days_back_filters_old(self):
        recs = garmin.import_garmin(self.json, days_back=1)
        self.assertEqual(recs, [])

    def test_summarize(self):
        recs = garmin.import_garmin(self.json)
        s = garmin.summarize(recs)
        self.assertEqual(s["source"], "garmin")
        self.assertEqual(s["date_from"], "2024-06-01")
        self.assertEqual(s["date_to"], "2024-06-01")
        self.assertIn("hrv_rmssd_ms", s["metrics"])

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            garmin.import_garmin(os.path.join(self.dir, "nope.json"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
