import unittest

from openhealth import modules
from openhealth.modules import metabolic, skin


class MetabolicTests(unittest.TestCase):
    def test_summary_and_tir(self):
        s = metabolic.summarize_glucose([90, 100, 200, 70])  # one above range
        self.assertEqual(s["n"], 4)
        self.assertAlmostEqual(s["mean_mg_dl"], 115.0, places=2)
        self.assertAlmostEqual(s["time_in_range_pct"], 75.0, places=1)  # 3/4 in 70-180
        # GMI = 3.31 + 0.02392*115 = 6.06
        self.assertAlmostEqual(s["gmi_pct"], 6.06, places=2)

    def test_critical_glucose_red_flag(self):
        modules.load_builtin()
        m = modules.get_module("metabolic")
        res = m.compute({"date": "2024-06-01", "glucose_mg_dl": [320, 110]})
        self.assertTrue(any("red-flag" in i.get("tags", []) for i in res.insights))

    def test_low_tir_prompt_capped(self):
        modules.load_builtin()
        m = modules.get_module("metabolic")
        res = m.compute({"glucose_mg_dl": [200, 210, 90, 220]})  # TIR 25%
        tir = [i for i in res.insights if "review-needed" in i.get("tags", [])][0]
        self.assertLessEqual(tir["confidence"], 0.45)
        self.assertIn("?", tir["summary"])


class SkinTests(unittest.TestCase):
    def test_summarize_counts(self):
        obs = [
            {"body_zone": "eyes", "visible_attributes": ["redness", "dryness"]},
            {"body_zone": "eyes", "visible_attributes": ["redness"]},
        ]
        per = skin.summarize(obs)
        self.assertEqual(per["eyes"]["redness"], 2)
        self.assertEqual(per["eyes"]["dryness"], 1)

    def test_recurring_prompt(self):
        modules.load_builtin()
        m = modules.get_module("skin")
        obs = [{"body_zone": "eyes", "visible_attributes": ["irritation"]} for _ in range(3)]
        res = m.compute({"observations": obs})
        self.assertTrue(res.insights)
        self.assertIn("?", res.insights[0]["summary"])

    def test_invalid_zone_falls_back(self):
        per = skin.summarize([{"body_zone": "nope", "visible_attributes": ["x"]}])
        self.assertIn("custom", per)


class AllDomainsTests(unittest.TestCase):
    def test_six_domains_registered(self):
        modules.load_builtin()
        ids = {m.id for m in modules.all_modules()}
        self.assertEqual(
            {"pulse", "sleep", "cycle", "body", "metabolic", "skin"},
            ids & {"pulse", "sleep", "cycle", "body", "metabolic", "skin"},
        )


if __name__ == "__main__":
    unittest.main()
