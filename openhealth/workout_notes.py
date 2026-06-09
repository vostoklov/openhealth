"""Tolerant parser for free-text workout notes — stdlib only.

People log strength workouts as quick chat-style notes, RU or EN, in wildly
mixed formats (the reference sample is a real Bios journal line):

    жим 40кг×10
    bench 40kg x10
    20 кг x 25
    Сведение ... в тренажере 22 кг на 12/12/10
    Грудь жим гриф/10/12.5/12.5/12.5 вес на 25/15/10/10/7

``parse_workout_note`` turns such text into structured exercises with sets
(``weight_kg`` + ``reps``); anything it cannot read confidently goes to
``notes`` verbatim instead of being guessed at (core rule: no invented data).
The parser never raises on user text.

Assumptions, kept visible:
- "гриф" (empty barbell) is counted as ``BAR_WEIGHT_KG`` = 20 kg, the standard
  olympic bar; the original label is preserved on the set.
- In the "A/B/C вес на X/Y/Z" form the first list is per-set weights and the
  second per-set reps; unpaired tail items are dropped with a note.
- Weights are assumed kilograms (кг/kg or bare numbers alike).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

BAR_WEIGHT_KG = 20.0

# A weight token: a number ("40", "12.5", "12,5") or the bare-bar word.
_NUM = r"\d+(?:[.,]\d+)?"
_WEIGHT_TOKEN = r"(?:гриф|%s)" % _NUM

# Form A — paired lists: "<name> гриф/10/12.5 вес на 25/15/10",
# also "<name> 25/22.5 кг на 12/10".
_PAIRED_RE = re.compile(
    r"(?P<name>.*?)\s*"
    r"(?P<weights>%(w)s(?:\s*/\s*%(w)s)+)\s*(?:кг|kg)?\s*"
    r"(?:вес\s+на|на|x)\s*"
    r"(?P<reps>\d+(?:\s*/\s*\d+)+)\s*$" % {"w": _WEIGHT_TOKEN},
    re.IGNORECASE,
)

# Form B — fixed weight, one or more rep counts:
# "жим 40кг x10", "bench 40kg x10", "20 кг x 25", "22 кг на 12/12/10".
# finditer-friendly so "жим 40кг×10, 45кг×8" yields two sets for one name.
_FIXED_RE = re.compile(
    r"(?P<weight>%(w)s)\s*(?:кг|kg)?\s*"
    r"(?:x|на)\s*"
    r"(?P<reps>\d+(?:\s*/\s*\d+)*)" % {"w": _WEIGHT_TOKEN},
    re.IGNORECASE,
)

_SEGMENT_SPLIT_RE = re.compile(r"[\n;]+|\.(?=\s|$)")
_NAME_TRIM_RE = re.compile(r"^[\s,.:;\-—]+|[\s,.:;\-—]+$")


def _normalize(text: str) -> str:
    """Unify multiplication signs and decimal commas before matching."""
    out = text.replace("×", "x")
    # Cyrillic "х" acts as a multiplication sign only between digits/spaces
    # ("40х10", "40 х 10"); inside words ("хват") it must stay a letter.
    out = re.sub(r"(?<=[\d\s])[хХ](?=[\s\d])", "x", out)
    # Decimal comma only when glued between digits ("12,5"); a comma with a
    # following space ("...x10, 45кг...") stays a set separator.
    out = re.sub(r"(\d),(\d)", r"\1.\2", out)
    return out


def _weight_value(token: str) -> Dict[str, Any]:
    token = token.strip().lower()
    if token == "гриф":
        return {"weight_kg": BAR_WEIGHT_KG, "label": "гриф"}
    return {"weight_kg": float(token.replace(",", "."))}


def _clean_name(raw: str) -> str:
    name = _NAME_TRIM_RE.sub("", raw)
    # "Круговая: Сведение ..." — the part after the last colon is the exercise.
    if ":" in name:
        name = _NAME_TRIM_RE.sub("", name.rsplit(":", 1)[1])
    return name.strip()


def _parse_segment(segment: str) -> Optional[Dict[str, Any]]:
    """One sentence/line -> {exercise, sets, warnings} or None when unreadable."""
    paired = _PAIRED_RE.match(segment.strip())
    if paired:
        weights = [w for w in re.split(r"\s*/\s*", paired.group("weights")) if w]
        reps = [r for r in re.split(r"\s*/\s*", paired.group("reps")) if r]
        sets: List[Dict[str, Any]] = []
        for w, r in zip(weights, reps):
            entry = _weight_value(w)
            entry["reps"] = int(r)
            sets.append(entry)
        warnings: List[str] = []
        if len(weights) != len(reps):
            warnings.append(
                "unpaired weights/reps (%d vs %d), extra items dropped" % (len(weights), len(reps))
            )
        return {"exercise": _clean_name(paired.group("name")), "sets": sets, "warnings": warnings}

    matches = list(_FIXED_RE.finditer(segment))
    if not matches:
        return None
    sets = []
    for m in matches:
        base = _weight_value(m.group("weight"))
        for r in re.split(r"\s*/\s*", m.group("reps")):
            entry = dict(base)
            entry["reps"] = int(r)
            sets.append(entry)
    name = _clean_name(segment[: matches[0].start()])
    return {"exercise": name, "sets": sets, "warnings": []}


def parse_workout_note(text: str) -> Dict[str, Any]:
    """Parse a free-text workout note.

    Returns ``{"exercises": [{"exercise", "sets": [{"weight_kg", "reps",
    "label"?}], "warnings": []}], "notes": [unparsed segments]}``. Tolerant by
    design: never raises on user text, unknown lines land in ``notes``.
    """
    exercises: List[Dict[str, Any]] = []
    notes: List[str] = []
    if not text or not str(text).strip():
        return {"exercises": exercises, "notes": notes}

    for raw_segment in _SEGMENT_SPLIT_RE.split(_normalize(str(text))):
        segment = raw_segment.strip()
        if not segment:
            continue
        try:
            parsed = _parse_segment(segment)
        except (ValueError, OverflowError):
            parsed = None  # pathological numbers — keep the raw text instead
        if parsed is not None and parsed["sets"]:
            exercises.append(parsed)
        else:
            notes.append(segment)
    return {"exercises": exercises, "notes": notes}


def summarize_workouts(parsed: "Dict[str, Any] | List[Dict[str, Any]]") -> Dict[str, Any]:
    """Aggregate parse output: total volume (kg) and per-exercise breakdown.

    Accepts either ``parse_workout_note`` output or a bare exercise list.
    Volume = sum(weight_kg * reps) over sets that have both numbers.
    """
    exercises = parsed.get("exercises", []) if isinstance(parsed, dict) else list(parsed)
    per_exercise: Dict[str, Dict[str, Any]] = {}
    for ex in exercises:
        name = ex.get("exercise") or "unknown"
        slot = per_exercise.setdefault(name, {"exercise": name, "volume_kg": 0.0, "sets": 0, "reps": 0})
        for s in ex.get("sets", []):
            weight = s.get("weight_kg")
            reps = s.get("reps")
            slot["sets"] += 1
            if isinstance(reps, (int, float)):
                slot["reps"] += int(reps)
            if isinstance(weight, (int, float)) and isinstance(reps, (int, float)):
                slot["volume_kg"] += float(weight) * float(reps)

    breakdown = sorted(per_exercise.values(), key=lambda e: e["volume_kg"], reverse=True)
    for entry in breakdown:
        entry["volume_kg"] = round(entry["volume_kg"], 1)
    return {
        "total_volume_kg": round(sum(e["volume_kg"] for e in breakdown), 1),
        "exercise_count": len(breakdown),
        "set_count": sum(e["sets"] for e in breakdown),
        "exercises": breakdown,
        "top_exercises": [e["exercise"] for e in breakdown[:3]],
    }
