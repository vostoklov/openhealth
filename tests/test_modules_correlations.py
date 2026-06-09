import tempfile
import unittest
from pathlib import Path

from openhealth import index, modules
from openhealth.modules import correlations


def _alternating_pairs(yes_recovery, no_recovery, n_each):
    """Build n_each yes-days and n_each no-days, alternating (many switches)."""
    pairs = []
    day = 1
    for i in range(n_each):
        pairs.append({"date": "2026-05-%02d" % day, "yes": True, "recovery": yes_recovery})
        day += 1
        pairs.append({"date": "2026-05-%02d" % day, "yes": False, "recovery": no_recovery})
        day += 1
    return pairs


def _blocked_pairs(yes_recovery, no_recovery, n_each):
    """All yes-days first, then all no-days (only one switch -> ABAB-weak)."""
    pairs = []
    day = 1
    for _ in range(n_each):
        pairs.append({"date": "2026-05-%02d" % day, "yes": True, "recovery": yes_recovery})
        day += 1
    for _ in range(n_each):
        pairs.append({"date": "2026-05-%02d" % day, "yes": False, "recovery": no_recovery})
        day += 1
    return pairs


class BehaviorImpactTests(unittest.TestCase):
    def test_impact_positive(self):
        stats = correlations.behavior_impact(_alternating_pairs(70.0, 55.0, 6))
        self.assertIsNotNone(stats)
        self.assertEqual(stats["n_yes"], 6)
        self.assertEqual(stats["n_no"], 6)
        self.assertEqual(stats["mean_recovery_yes"], 70.0)
        self.assertEqual(stats["mean_recovery_no"], 55.0)
        self.assertEqual(stats["impact"], 15.0)
        self.assertEqual(stats["direction"], "positive")
        self.assertEqual(stats["size"], "moderate")

    def test_impact_negative(self):
        stats = correlations.behavior_impact(_alternating_pairs(50.0, 62.0, 5))
        self.assertEqual(stats["impact"], -12.0)
        self.assertEqual(stats["direction"], "negative")

    def test_below_threshold_returns_none(self):
        # 4 yes / 6 no -> below the 5-yes minimum.
        pairs = (
            [{"date": "2026-05-%02d" % d, "yes": True, "recovery": 70.0} for d in range(1, 5)]
            + [{"date": "2026-05-%02d" % d, "yes": False, "recovery": 55.0} for d in range(5, 11)]
        )
        self.assertIsNone(correlations.behavior_impact(pairs))

    def test_drops_days_without_recovery(self):
        pairs = _alternating_pairs(70.0, 55.0, 5)
        pairs.append({"date": "2026-05-30", "yes": True, "recovery": None})
        stats = correlations.behavior_impact(pairs)
        self.assertEqual(stats["n_yes"], 5)  # the None-recovery day is excluded

    def test_switch_count(self):
        many = correlations.behavior_impact(_alternating_pairs(70.0, 55.0, 5))
        blocked = correlations.behavior_impact(_blocked_pairs(70.0, 55.0, 5))
        self.assertGreater(many["switches"], blocked["switches"])
        self.assertEqual(blocked["switches"], 1)


class CorrelationActionTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_actionable_insight_has_grade_and_action_text(self):
        m = modules.get_module("correlations")
        res = m.compute({
            "behaviors": [
                {"behavior_id": "recovery_activities.meditation",
                 "pairs": _alternating_pairs(72.0, 55.0, 6)}
            ]
        })
        self.assertEqual(len(res.insights), 1)
        ins = res.insights[0]
        # Action phrasing, not a bare number.
        self.assertIn("Try", ins["statement"])
        self.assertIn("Meditation", ins["statement"])
        # Personal correlation is graded and capped (never high confidence).
        self.assertIn(ins["metadata"]["confidence_grade"], {"C2", "C3"})
        self.assertLessEqual(ins["confidence"], 0.45)
        # C3 and below is framed as a question.
        self.assertIn("?", ins["summary"])

    def test_blocked_data_is_weaker_than_alternating(self):
        m = modules.get_module("correlations")
        alt = m.compute({"behaviors": [
            {"behavior_id": "recovery_activities.meditation", "pairs": _alternating_pairs(72.0, 55.0, 6)}
        ]}).insights[0]
        blk = m.compute({"behaviors": [
            {"behavior_id": "recovery_activities.meditation", "pairs": _blocked_pairs(72.0, 55.0, 6)}
        ]}).insights[0]
        # Alternating (more switches) earns C3; blocked (one switch) stays C2.
        self.assertEqual(alt["metadata"]["confidence_grade"], "C3")
        self.assertEqual(blk["metadata"]["confidence_grade"], "C2")

    def test_negligible_impact_is_dropped(self):
        m = modules.get_module("correlations")
        res = m.compute({"behaviors": [
            {"behavior_id": "nutrition.breakfast", "pairs": _alternating_pairs(60.0, 59.0, 6)}
        ]})
        # impact 1.0 < SMALL_IMPACT -> negligible -> not surfaced
        self.assertEqual(len(res.insights), 0)

    def test_insights_sorted_by_magnitude(self):
        m = modules.get_module("correlations")
        res = m.compute({"behaviors": [
            {"behavior_id": "recovery_activities.meditation", "pairs": _alternating_pairs(65.0, 58.0, 6)},  # +7
            {"behavior_id": "lifestyle.alcohol", "pairs": _alternating_pairs(45.0, 65.0, 6)},  # -20
        ]})
        impacts = [abs(i["metadata"]["impact"]) for i in res.insights]
        self.assertEqual(impacts, sorted(impacts, reverse=True))
        self.assertEqual(res.insights[0]["metadata"]["behavior_id"], "lifestyle.alcohol")


class CorrelationsFromIndexTests(unittest.TestCase):
    def setUp(self):
        modules.load_builtin()

    def test_from_index_pairs_journal_with_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = Path(tmp) / "oh.sqlite3"
            index.init_db(db)
            # 6 yes + 6 no journal days for alcohol, each with a recovery score.
            day = 1
            for i in range(6):
                for yes, rec in ((True, 50.0), (False, 65.0)):
                    d = "2026-05-%02d" % day
                    day += 1
                    index.upsert_record(db, {
                        "id": f"obs-journal-{d}-lifestyle.alcohol",
                        "record_type": "Observation", "source_id": "journal",
                        "title": "j", "summary": "s", "artifact_ids": [],
                        "evidence_class": "personal", "confidence": 0.9, "date": d,
                        "observation_kind": "journal_entry", "metric_name": "lifestyle.alcohol",
                        "value": yes,
                        "metadata": {"behavior_id": "lifestyle.alcohol", "category": "lifestyle"},
                    })
                    index.upsert_record(db, {
                        "id": f"obs-recovery-score-{d}",
                        "record_type": "Observation", "source_id": "recovery",
                        "title": "r", "summary": "s", "artifact_ids": [],
                        "evidence_class": "derived-metric", "confidence": 0.9, "date": d,
                        "observation_kind": "recovery_score", "metric_name": "recovery_score",
                        "value": rec,
                    })
            behaviors = correlations.from_index(db, window_days=90, as_of="2026-05-31")
            self.assertEqual(len(behaviors), 1)
            self.assertEqual(behaviors[0]["behavior_id"], "lifestyle.alcohol")
            stats = correlations.behavior_impact(behaviors[0]["pairs"])
            self.assertEqual(stats["impact"], -15.0)  # 50 - 65


if __name__ == "__main__":
    unittest.main()
