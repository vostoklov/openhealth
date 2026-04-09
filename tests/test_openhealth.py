import json
import os
import tempfile
import unittest
from pathlib import Path

from openhealth import index
from openhealth.contexts import refresh_contexts
from openhealth.ingest import ingest_path, init_workspace
from openhealth.storage import ensure_repo_structure


class OpenHealthIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        init_workspace(self.root)
        os.environ["OPENHEALTH_WEATHER_PROVIDER"] = "static"
        os.environ["OPENHEALTH_WEATHER_STATIC"] = json.dumps(
            {
                "Budapest|2024-05-01": {"provider": "static", "temperature_c_max": 24, "conditions": "sunny"},
                "Budapest|2024-05-02": {"provider": "static", "temperature_c_max": 19, "conditions": "windy"}
            }
        )

    def tearDown(self):
        os.environ.pop("OPENHEALTH_WEATHER_PROVIDER", None)
        os.environ.pop("OPENHEALTH_WEATHER_STATIC", None)
        self.temp_dir.cleanup()

    def test_full_ingest_flow(self):
        whoop = self.root / "fixtures" / "whoop.csv"
        whoop.parent.mkdir(parents=True, exist_ok=True)
        whoop.write_text(
            "date,recovery,sleep_hours,strain\n"
            "2024-05-01,71,7.5,12.1\n"
            "2024-05-02,48,6.1,14.2\n",
            encoding="utf-8",
        )
        whoop_result = ingest_path(self.root, "whoop", whoop, location="Budapest")
        self.assertEqual(whoop_result["artifacts_imported"], 1)

        report = self.root / "fixtures" / "atlas-dna.pdf"
        report.write_bytes(b"%PDF-pretend")
        report.with_name(report.name + ".meta.json").write_text(
            json.dumps(
                {
                    "title": "Atlas DNA",
                    "date": "2024-02-10",
                    "location": "Budapest",
                    "summary": "Historic DNA panel with methylation and detox-related markers.",
                    "observations": [
                        {
                            "metric_name": "Methylation marker",
                            "value": "elevated",
                            "summary": "Manual extraction from historical DNA report.",
                            "confidence": 0.5
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        ingest_path(self.root, "document-tests", report)

        message = self.root / "fixtures" / "stress-note.md"
        message.write_text(
            "---\n"
            "title: Hard week at work\n"
            "date: 2024-05-02\n"
            "location: Budapest\n"
            "themes: stress, sleep\n"
            "tags: personal, work\n"
            "---\n\n"
            "I had a few intense conversations and felt depleted for several days.",
            encoding="utf-8",
        )
        ingest_path(self.root, "messages", message)

        intervention = self.root / "fixtures" / "skin-routine.md"
        intervention.write_text(
            "---\n"
            "title: New skin routine\n"
            "start_date: 2024-05-02\n"
            "location: Budapest\n"
            "tags: skincare, protocol\n"
            "subject: azelaic acid\n"
            "status: active\n"
            "cadence: nightly\n"
            "---\n\n"
            "Started applying the product nightly.",
            encoding="utf-8",
        )
        ingest_path(self.root, "product-usage", intervention)

        reference = self.root / "fixtures" / "reddit-case.md"
        reference.write_text(
            "---\n"
            "title: Similar routine example\n"
            "origin: Reddit thread\n"
            "applicability: weak analogy only\n"
            "tags: reference, skincare\n"
            "---\n\n"
            "Another person described a similar response pattern after changing routine.",
            encoding="utf-8",
        )
        ingest_path(self.root, "reference-examples", reference)

        envelope = self.root / "fixtures" / "telegram-envelope.json"
        envelope.write_text(
            json.dumps(
                {
                    "submission_id": "tg-001",
                    "submitted_at": "2024-05-03T08:30:00Z",
                    "channel": "telegram",
                    "author": "user",
                    "text": "Breakfast photo plus a quick note about digestion.",
                    "location": "Budapest",
                    "attachments": [{"type": "image", "filename": "meal.jpg"}],
                    "tags": ["meal", "telegram"]
                }
            ),
            encoding="utf-8",
        )
        ingest_path(self.root, "telegram-intake", envelope)

        duplicate_result = ingest_path(self.root, "whoop", whoop, location="Budapest")
        self.assertEqual(duplicate_result["duplicates_skipped"], 1)

        paths = ensure_repo_structure(self.root)
        refresh_contexts(paths, index)
        records = index.list_records(paths.db_path)
        artifacts = index.list_artifacts(paths.db_path)

        record_types = {record["record_type"] for record in records}
        self.assertIn("Observation", record_types)
        self.assertIn("TimelineEvent", record_types)
        self.assertIn("ContextNote", record_types)
        self.assertIn("Intervention", record_types)
        self.assertIn("ReferenceCase", record_types)
        self.assertIn("InsightHypothesis", record_types)

        weather_records = [record for record in records if record["record_type"] == "Observation" and "weather" in record.get("tags", [])]
        self.assertTrue(weather_records)
        self.assertEqual(len(artifacts), 6)

        patterns = (self.root / "contexts" / "patterns.md").read_text(encoding="utf-8")
        self.assertIn("correlation prompt", patterns)
        quick_brief = (self.root / "contexts" / "quick-brief.md").read_text(encoding="utf-8")
        self.assertIn("OpenHealth currently tracks", quick_brief)
        source_status = (self.root / "contexts" / "source-status.md").read_text(encoding="utf-8")
        self.assertIn("reference-examples", source_status)


if __name__ == "__main__":
    unittest.main()
