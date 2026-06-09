import os
import tempfile
import unittest
import zipfile

from openhealth.connectors import apple_health

EXPORT_XML = """<?xml version="1.0" encoding="UTF-8"?>
<HealthData locale="en_US">
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2024-06-01 09:00:00 +0000" endDate="2024-06-01 09:10:00 +0000" value="1000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2024-06-01 18:00:00 +0000" endDate="2024-06-01 18:10:00 +0000" value="2000"/>
 <Record type="HKQuantityTypeIdentifierStepCount" unit="count" startDate="2024-06-02 09:00:00 +0000" endDate="2024-06-02 09:10:00 +0000" value="500"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" startDate="2024-06-01 09:00:00 +0000" endDate="2024-06-01 09:00:01 +0000" value="60"/>
 <Record type="HKQuantityTypeIdentifierHeartRate" unit="count/min" startDate="2024-06-01 21:00:00 +0000" endDate="2024-06-01 21:00:01 +0000" value="80"/>
 <Record type="HKQuantityTypeIdentifierBodyMass" unit="lb" startDate="2024-06-01 07:00:00 +0000" endDate="2024-06-01 07:00:00 +0000" value="180"/>
 <Record type="HKQuantityTypeIdentifierHeartRateVariabilitySDNN" unit="ms" startDate="2024-06-01 07:00:00 +0000" endDate="2024-06-01 07:00:00 +0000" value="45"/>
 <Record type="HKCategoryTypeIdentifierSleepAnalysis" value="HKCategoryValueSleepAnalysisAsleepCore" startDate="2024-06-01 23:00:00 +0000" endDate="2024-06-02 06:00:00 +0000"/>
</HealthData>
"""


def _by(records, metric, date=None):
    for r in records:
        if r["metric_name"] == metric and (date is None or r["date"] == date):
            return r
    return None


class AppleHealthImportTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.xml = os.path.join(self.dir, "export.xml")
        with open(self.xml, "w", encoding="utf-8") as f:
            f.write(EXPORT_XML)

    def test_daily_aggregation(self):
        recs = apple_health.import_apple_health(self.xml)
        self.assertEqual(_by(recs, "steps", "2024-06-01")["value"], 3000)   # sum
        self.assertEqual(_by(recs, "steps", "2024-06-02")["value"], 500)
        self.assertEqual(_by(recs, "heart_rate_bpm", "2024-06-01")["value"], 70.0)  # mean
        self.assertEqual(_by(recs, "hrv_sdnn_ms", "2024-06-01")["value"], 45.0)

    def test_weight_lb_to_kg(self):
        recs = apple_health.import_apple_health(self.xml)
        w = _by(recs, "weight_kg")
        self.assertEqual(w["unit"], "kg")
        self.assertAlmostEqual(w["value"], round(180 * 0.45359237, 3), places=3)  # 81.647

    def test_sleep_duration_crosses_midnight(self):
        recs = apple_health.import_apple_health(self.xml)
        s = _by(recs, "sleep_duration_h", "2024-06-01")  # bucketed by start date
        self.assertEqual(s["value"], 7.0)  # 23:00 -> 06:00

    def test_observation_shape_and_tags(self):
        recs = apple_health.import_apple_health(self.xml)
        steps = _by(recs, "steps", "2024-06-01")
        self.assertEqual(steps["record_type"], "Observation")
        self.assertEqual(steps["source_id"], "apple-health")
        self.assertIn("body", steps["tags"])
        self.assertIn("apple-health", steps["tags"])

    def test_zip_input(self):
        zpath = os.path.join(self.dir, "export.zip")
        with zipfile.ZipFile(zpath, "w") as z:
            z.write(self.xml, "apple_health_export/export.xml")
        recs = apple_health.import_apple_health(zpath)
        self.assertEqual(_by(recs, "steps", "2024-06-01")["value"], 3000)

    def test_days_back_filters_old_records(self):
        # all fixture dates are in 2024 (long past) -> days_back=1 yields nothing
        recs = apple_health.import_apple_health(self.xml, days_back=1)
        self.assertEqual(len(recs), 0)

    def test_summarize(self):
        recs = apple_health.import_apple_health(self.xml)
        s = apple_health.summarize(recs)
        self.assertEqual(s["date_from"], "2024-06-01")
        self.assertEqual(s["date_to"], "2024-06-02")
        self.assertIn("steps", s["metrics"])
        self.assertGreaterEqual(s["total_records"], 5)


if __name__ == "__main__":
    unittest.main()
