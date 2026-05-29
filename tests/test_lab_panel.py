import json
import os
import tempfile
import unittest
from pathlib import Path

from openhealth import index
from openhealth import evidence
from openhealth import reference_ranges
from openhealth.ingest import ingest_path, init_workspace
from openhealth.storage import ensure_repo_structure


class ReferenceRangeTests(unittest.TestCase):
    def test_match_marker_by_alias(self):
        self.assertEqual(reference_ranges.match_marker("Hemoglobin").key, "hemoglobin")
        self.assertEqual(reference_ranges.match_marker("HgB").key, "hemoglobin")
        self.assertEqual(reference_ranges.match_marker("Vitamin D (25-OH)").key, "vitamin_d")
        self.assertIsNone(reference_ranges.match_marker("Unobtainium"))

    def test_flag_low_normal_high(self):
        low = reference_ranges.assess_marker("Vitamin D (25-OH)", value=12.0)
        self.assertEqual(low["flag"], "low")
        ok = reference_ranges.assess_marker("Vitamin D (25-OH)", value=45.0)
        self.assertEqual(ok["flag"], "normal")
        high = reference_ranges.assess_marker("Total cholesterol", value=240.0)
        self.assertEqual(high["flag"], "high")

    def test_report_range_preferred_over_fallback(self):
        a = reference_ranges.assess_marker(
            "Glucose", value=105.0, report_low=70.0, report_high=110.0
        )
        # 105 is high vs fallback (70-99) but normal vs the report's 70-110.
        self.assertEqual(a["flag"], "normal")
        self.assertEqual(a["reference_source"], "report")

    def test_unit_conversion_to_si(self):
        a = reference_ranges.assess_marker("Glucose", value=100.0)
        # 100 mg/dL * 0.0555 = 5.55 mmol/L
        self.assertAlmostEqual(a["value_si"], 5.55, places=2)
        self.assertEqual(a["si_unit"], "mmol/L")

    def test_sex_specific_range(self):
        male = reference_ranges.assess_marker("Ferritin", value=20.0, sex="male")
        self.assertEqual(male["flag"], "low")  # 20 < 30 for males
        female = reference_ranges.assess_marker("Ferritin", value=20.0, sex="female")
        self.assertEqual(female["flag"], "normal")  # 15-150 for females


class EvidenceTests(unittest.TestCase):
    def test_personal_pattern_capped_until_validated(self):
        capped = evidence.cap_personal_pattern(evidence.Confidence.C5, validated_switches=0)
        self.assertEqual(capped, evidence.Confidence.C2)
        validated = evidence.cap_personal_pattern(evidence.Confidence.C5, validated_switches=1)
        self.assertEqual(validated, evidence.Confidence.C3)

    def test_low_confidence_framed_as_question(self):
        framed = evidence.frame_statement("late caffeine lowers deep sleep", evidence.Confidence.C2)
        self.assertIn("?", framed)
        stated = evidence.frame_statement("vitamin D supports bone health", evidence.Confidence.C5)
        self.assertNotIn("Possible pattern to check", stated)

    def test_text_red_flags(self):
        hits = evidence.scan_text_red_flags("I had chest pain this morning")
        self.assertTrue(any(f.code == "chest_pain" for f in hits))
        self.assertEqual(evidence.scan_text_red_flags("felt a bit tired"), [])

    def test_critical_lab(self):
        flag = evidence.check_critical_lab("glucose", 320.0)
        self.assertIsNotNone(flag)
        self.assertEqual(flag.urgency, "urgent")
        self.assertIsNone(evidence.check_critical_lab("glucose", 95.0))


class LabPanelIngestTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        init_workspace(self.root)
        os.environ["OPENHEALTH_WEATHER_PROVIDER"] = "static"
        os.environ["OPENHEALTH_WEATHER_STATIC"] = "{}"

    def tearDown(self):
        os.environ.pop("OPENHEALTH_WEATHER_PROVIDER", None)
        os.environ.pop("OPENHEALTH_WEATHER_STATIC", None)
        self.temp_dir.cleanup()

    def _write_panel(self, markers, sex="male", date="2024-06-01"):
        panel = self.root / "fixtures" / "panel.json"
        panel.parent.mkdir(parents=True, exist_ok=True)
        panel.write_text(
            json.dumps({"date": date, "sex": sex, "markers": markers}),
            encoding="utf-8",
        )
        return panel

    def test_lab_panel_creates_marker_observations(self):
        panel = self._write_panel([
            {"name": "Hemoglobin", "value": 14.5, "unit": "g/dL"},
            {"name": "Vitamin D (25-OH)", "value": 12.0, "unit": "ng/mL"},
            {"name": "TSH", "value": 2.1, "unit": "mIU/L"},
        ])
        result = ingest_path(self.root, "lab-panel", panel)
        self.assertEqual(result["artifacts_imported"], 1)

        paths = ensure_repo_structure(self.root)
        records = index.list_records(paths.db_path)
        lab_obs = [r for r in records if r.get("metric_name") in ("hemoglobin", "vitamin_d", "tsh")]
        self.assertEqual(len(lab_obs), 3)

        vit_d = next(r for r in records if r.get("metric_name") == "vitamin_d")
        self.assertEqual(vit_d["metadata"]["flag"], "low")
        self.assertEqual(vit_d["metadata"]["loinc"], "1989-3")

        # An out-of-range marker should raise a (non-critical) review alert.
        alerts = [r for r in records if r["record_type"] == "PatternAlert"]
        self.assertTrue(alerts)
        self.assertIn("out-of-range", alerts[0]["tags"])

    def test_critical_value_raises_red_flag(self):
        panel = self._write_panel([
            {"name": "Glucose", "value": 320.0, "unit": "mg/dL"},
        ])
        ingest_path(self.root, "lab-panel", panel)
        paths = ensure_repo_structure(self.root)
        records = index.list_records(paths.db_path)
        alerts = [r for r in records if r["record_type"] == "PatternAlert"]
        self.assertTrue(any("red-flag" in a["tags"] for a in alerts))
        glucose = next(r for r in records if r.get("metric_name") == "glucose")
        self.assertIn("red_flag", glucose["metadata"])

    def test_symptom_text_raises_safety_alert(self):
        note = self.root / "fixtures" / "symptom.md"
        note.parent.mkdir(parents=True, exist_ok=True)
        note.write_text(
            "---\ntitle: Bad morning\ndate: 2024-06-02\n---\n\n"
            "Woke up with chest pain and shortness of breath.",
            encoding="utf-8",
        )
        ingest_path(self.root, "messages", note)
        paths = ensure_repo_structure(self.root)
        records = index.list_records(paths.db_path)
        alerts = [r for r in records if r["record_type"] == "PatternAlert"]
        self.assertTrue(any("see-clinician" in a["tags"] for a in alerts))


if __name__ == "__main__":
    unittest.main()
