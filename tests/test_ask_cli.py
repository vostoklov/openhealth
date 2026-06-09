import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from openhealth.ask import run_ask
from openhealth.ingest import init_workspace
from openhealth.storage import ensure_repo_structure


class AskCliTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        init_workspace(self.root)
        self.paths = ensure_repo_structure(self.root)
        (self.paths.contexts / "quick-brief.md").write_text(
            "# Quick Brief\n\n"
            "OpenHealth currently tracks 1 source batch.\n"
            "- `2026-05-08` [Observation] WHOOP recovery recovery score\n",
            encoding="utf-8",
        )
        (self.paths.timeline_context / "current.md").write_text(
            "# Timeline\n\n"
            "- `2026-05-08` [TimelineEvent] WHOOP recovery: Recovery synced for 2026-05-08.\n",
            encoding="utf-8",
        )
        (self.paths.contexts / "profile.md").write_text(
            "# Profile\n\n"
            "- Current priority: protect recovery before the workshop.\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_run_ask_prints_offline_fallback_without_api_key(self):
        output = StringIO()
        errors = StringIO()
        with patch.dict("os.environ", {}, clear=True):
            code = run_ask(self.root, "What changed today?", out=output, err=errors)
        self.assertEqual(code, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertIn("No Anthropic API key found", output.getvalue())
        self.assertIn("[Q1]", output.getvalue())
        self.assertIn("[T1]", output.getvalue())

    def test_run_ask_reports_missing_contexts(self):
        (self.paths.timeline_context / "current.md").unlink()
        output = StringIO()
        errors = StringIO()
        with patch.dict("os.environ", {}, clear=True):
            code = run_ask(self.root, "What changed today?", out=output, err=errors)
        self.assertEqual(code, 1)
        self.assertIn("contexts/timeline/current.md", errors.getvalue())
        self.assertIn("refresh-contexts", errors.getvalue())

    def test_run_ask_prints_cited_records(self):
        output = StringIO()
        errors = StringIO()
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key"}, clear=True):
            with patch(
                "openhealth.ask.fetch_anthropic_answer",
                return_value="You should keep today light because recovery is the freshest signal [Q2] and it was synced today [T1].",
            ):
                code = run_ask(self.root, "What should I do today?", stream=False, out=output, err=errors)
        self.assertEqual(code, 0)
        self.assertEqual(errors.getvalue(), "")
        self.assertIn("keep today light", output.getvalue())
        self.assertIn("Cited records:", output.getvalue())
        self.assertIn("[Q2] contexts/quick-brief.md", output.getvalue())
        self.assertIn("[T1] contexts/timeline/current.md", output.getvalue())


if __name__ == "__main__":
    unittest.main()
