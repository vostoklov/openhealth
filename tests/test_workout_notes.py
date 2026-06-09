import unittest

from openhealth import workout_notes

BIOS_LINE = (
    "Грудь жим гриф/10/12.5/12.5/12.5 вес на 25/15/10/10/7. "
    "Круговая: Сведение на середину груди в тренажере черном 22 кг на 12/12/10"
)


class ParseFormatsTests(unittest.TestCase):
    def test_ru_compact_multiplication(self):
        out = workout_notes.parse_workout_note("жим 40кг×10")
        self.assertEqual(len(out["exercises"]), 1)
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "жим")
        self.assertEqual(ex["sets"], [{"weight_kg": 40.0, "reps": 10}])
        self.assertEqual(out["notes"], [])

    def test_en_format(self):
        out = workout_notes.parse_workout_note("bench 40kg x10")
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "bench")
        self.assertEqual(ex["sets"], [{"weight_kg": 40.0, "reps": 10}])

    def test_bare_weight_reps_without_exercise(self):
        out = workout_notes.parse_workout_note("20 кг x 25")
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "")
        self.assertEqual(ex["sets"], [{"weight_kg": 20.0, "reps": 25}])

    def test_fixed_weight_rep_list(self):
        out = workout_notes.parse_workout_note("Сведение в тренажере 22 кг на 12/12/10")
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "Сведение в тренажере")
        self.assertEqual([s["reps"] for s in ex["sets"]], [12, 12, 10])
        self.assertTrue(all(s["weight_kg"] == 22.0 for s in ex["sets"]))

    def test_comma_separated_sets(self):
        out = workout_notes.parse_workout_note("жим 40кг×10, 45кг×8")
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "жим")
        self.assertEqual(ex["sets"], [{"weight_kg": 40.0, "reps": 10}, {"weight_kg": 45.0, "reps": 8}])

    def test_cyrillic_x_and_decimal_comma(self):
        out = workout_notes.parse_workout_note("тяга 12,5 кг х 12")
        ex = out["exercises"][0]
        self.assertEqual(ex["exercise"], "тяга")
        self.assertEqual(ex["sets"], [{"weight_kg": 12.5, "reps": 12}])

    def test_bios_battle_line(self):
        out = workout_notes.parse_workout_note(BIOS_LINE)
        self.assertEqual(len(out["exercises"]), 2)
        self.assertEqual(out["notes"], [])

        press = out["exercises"][0]
        self.assertEqual(press["exercise"], "Грудь жим")
        self.assertEqual(len(press["sets"]), 5)
        # "гриф" = empty bar, counted as 20 kg with the label preserved.
        self.assertEqual(press["sets"][0], {"weight_kg": 20.0, "label": "гриф", "reps": 25})
        self.assertEqual([s["weight_kg"] for s in press["sets"]], [20.0, 10.0, 12.5, 12.5, 12.5])
        self.assertEqual([s["reps"] for s in press["sets"]], [25, 15, 10, 10, 7])

        fly = out["exercises"][1]
        # "Круговая:" prefix is context, the exercise is what follows the colon.
        self.assertEqual(fly["exercise"], "Сведение на середину груди в тренажере черном")
        self.assertEqual([s["reps"] for s in fly["sets"]], [12, 12, 10])
        self.assertTrue(all(s["weight_kg"] == 22.0 for s in fly["sets"]))

    def test_unknown_lines_go_to_notes(self):
        out = workout_notes.parse_workout_note("жим 40кг x10\nустал, болело плечо")
        self.assertEqual(len(out["exercises"]), 1)
        self.assertEqual(out["notes"], ["устал, болело плечо"])

    def test_never_raises_on_garbage(self):
        for text in ("", "   ", None, "...", "a/b/c на x/y", "12345"):
            out = workout_notes.parse_workout_note(text)
            self.assertIn("exercises", out)
            self.assertIn("notes", out)

    def test_unpaired_lists_warn_not_crash(self):
        out = workout_notes.parse_workout_note("жим 40/45/50 на 10/8")
        ex = out["exercises"][0]
        self.assertEqual(len(ex["sets"]), 2)
        self.assertTrue(ex["warnings"])


class SummarizeTests(unittest.TestCase):
    def test_volume_and_top_exercises(self):
        parsed = workout_notes.parse_workout_note(BIOS_LINE)
        summary = workout_notes.summarize_workouts(parsed)
        # Press: 20*25 + 10*15 + 12.5*(10+10+7) = 987.5; fly: 22*34 = 748.
        self.assertEqual(summary["total_volume_kg"], 1735.5)
        self.assertEqual(summary["exercise_count"], 2)
        self.assertEqual(summary["set_count"], 8)
        self.assertEqual(summary["top_exercises"][0], "Грудь жим")
        by_name = {e["exercise"]: e for e in summary["exercises"]}
        self.assertEqual(by_name["Грудь жим"]["volume_kg"], 987.5)
        self.assertEqual(by_name["Сведение на середину груди в тренажере черном"]["volume_kg"], 748.0)

    def test_accepts_bare_exercise_list_and_empty(self):
        summary = workout_notes.summarize_workouts([])
        self.assertEqual(summary["total_volume_kg"], 0)
        summary = workout_notes.summarize_workouts(
            [{"exercise": "жим", "sets": [{"weight_kg": 40.0, "reps": 10}]}]
        )
        self.assertEqual(summary["total_volume_kg"], 400.0)


if __name__ == "__main__":
    unittest.main()
