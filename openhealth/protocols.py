"""Turn cautious insights and personal correlations into n-of-1 protocols.

An ``Insight`` says "here is a possible problem"; a ``Protocol`` says "here is
the one change to test and exactly how we'll know if it helped". This is what
moves a finding from a *weak personal signal* (C2) toward something trustworthy:
a minimal single-subject experiment (n-of-1), usually an ABAB switch with a
baseline and a pre-stated success criterion.

Design rules
------------
- One intervention per protocol. Change one thing at a time or the result is
  uninterpretable.
- A concrete, numeric success criterion stated up front (no moving goalposts).
- ``confidence_cap`` is C2 while the protocol is unfinished: until the switch
  actually plays out, the underlying belief stays a weak personal signal
  (canon: ``openhealth.evidence``). Completing the n-of-1 is what can lift it.
- A safety note on every protocol. This is self-observation, not treatment;
  red-flag symptoms route to a clinician.

Pure stdlib.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from . import evidence
from . import insights as insights_mod

MAX_ACTIVE_PROTOCOLS = 3

# Default safety note shared by all protocols; some kinds strengthen it.
DEFAULT_SAFETY_NOTE = (
    "Это самонаблюдение (n-of-1), а не лечение. Меняйте только один фактор за раз. "
    "При тревожных симптомах обратитесь к врачу."
)
RED_STREAK_SAFETY_NOTE = (
    "Затяжная серия низкого восстановления вместе с симптомами (жар, боль, сильная "
    "усталость) - повод сначала показаться врачу, а не запускать эксперимент."
)

# Behavior-id / category fragments that look like classic HRV suppressors. Used
# to point an HRV-downtrend protocol at a concrete trigger when correlations
# already implicate one.
_HRV_TRIGGER_HINTS = ("alcohol", "алког", "screen", "экран", "late", "поздн", "caffeine", "кофеин")


@dataclass
class Protocol:
    """A single n-of-1 experiment proposal."""

    id: str
    hypothesis_ru: str
    intervention_ru: str                # exactly one change
    metric: str                         # what we measure
    baseline_days: int
    intervention_days: int
    schema: str                         # "ABAB" | "AB"
    success_criteria_ru: str            # concrete, numeric, pre-stated
    confidence_cap: evidence.Confidence = evidence.Confidence.C2
    safety_note_ru: str = DEFAULT_SAFETY_NOTE

    def to_dict(self) -> Dict[str, Any]:
        meta = evidence.CONFIDENCE_META[self.confidence_cap]
        return {
            "id": self.id,
            "hypothesis_ru": self.hypothesis_ru,
            "intervention_ru": self.intervention_ru,
            "metric": self.metric,
            "baseline_days": self.baseline_days,
            "intervention_days": self.intervention_days,
            "schema": self.schema,
            "success_criteria_ru": self.success_criteria_ru,
            "confidence_cap": self.confidence_cap.value,
            "confidence_cap_label": meta["label"],
            "safety_note_ru": self.safety_note_ru,
        }


# --- from a single insight ---------------------------------------------------

def _kind(insight: "insights_mod.Insight") -> str:
    return insight.data.get("kind") or insight.id.replace("insight-", "")


def _hrv_intervention(correlations: Optional[List[Dict[str, Any]]]) -> str:
    """Point the HRV protocol at a concrete trigger if one is implicated."""
    for c in correlations or []:
        meta = c.get("metadata", {})
        if meta.get("direction") != "negative":
            continue
        hay = "%s %s %s" % (
            meta.get("behavior_id", ""), meta.get("category", ""), c.get("title", "")
        )
        hay = hay.lower()
        if any(h in hay for h in _HRV_TRIGGER_HINTS):
            name = c.get("title", "").replace("Impact: ", "").strip() or "этот фактор"
            return "Уберите '%s' на 7 дней (по вашим данным он связан со снижением)." % name
    return "Сделайте 7 дней восстановительного режима: отбой на 30-45 минут раньше, без вечернего алкоголя."


def from_insight(
    insight: "insights_mod.Insight",
    correlations: Optional[List[Dict[str, Any]]] = None,
) -> Optional[Protocol]:
    """Map one insight to a protocol template. Returns None if no template."""
    kind = _kind(insight)

    if kind == "sleep_debt":
        return Protocol(
            id="protocol-sleep_debt",
            hypothesis_ru="Если убрать недосып, среднее восстановление вырастет.",
            intervention_ru="Ложитесь на 45 минут раньше обычного.",
            metric="recovery",
            baseline_days=7,
            intervention_days=7,
            schema="ABAB",
            success_criteria_ru="Среднее recovery в фазах с ранним отбоем (B) выше, "
                                 "чем в обычных (A), на >= 5 пунктов.",
        )

    if kind == "hrv_downtrend":
        return Protocol(
            id="protocol-hrv_downtrend",
            hypothesis_ru="Снятие основной нагрузки на HRV вернёт его к личному baseline.",
            intervention_ru=_hrv_intervention(correlations),
            metric="hrv",
            baseline_days=7,
            intervention_days=7,
            schema="ABAB",
            success_criteria_ru="7-дневное среднее HRV в фазе вмешательства выше "
                                 "базового на >= 8% (возврат к baseline).",
        )

    if kind == "rhr_uptrend":
        return Protocol(
            id="protocol-rhr_uptrend",
            hypothesis_ru="Снижение вечерней нагрузки и алкоголя вернёт пульс покоя к baseline.",
            intervention_ru="Уберите вечерний алкоголь и добавьте 2 лёгких дня в неделю.",
            metric="rhr",
            baseline_days=7,
            intervention_days=7,
            schema="ABAB",
            success_criteria_ru="7-дневный пульс покоя в фазе вмешательства в пределах 2 уд/мин от baseline.",
        )

    if kind == "recovery_red_streak":
        return Protocol(
            id="protocol-recovery_red_streak",
            hypothesis_ru="Неделя приоритета восстановлению выводит recovery из красной зоны.",
            intervention_ru="7 дней приоритет сну и покою: ранний отбой, без "
                            "интенсивных тренировок и вечернего алкоголя.",
            metric="recovery",
            baseline_days=7,
            intervention_days=7,
            schema="AB",
            success_criteria_ru="Нет красных дней подряд; среднее recovery в фазе B выше, чем в A, на >= 7 пунктов.",
            safety_note_ru=RED_STREAK_SAFETY_NOTE,
        )

    if kind == "strain_recovery_mismatch":
        return Protocol(
            id="protocol-strain_recovery_mismatch",
            hypothesis_ru="Если привязать интенсивность к утреннему recovery, восстановление улучшится.",
            intervention_ru="Планируйте интенсивность по утреннему recovery: при recovery < 50 - только лёгкий день.",
            metric="recovery",
            baseline_days=7,
            intervention_days=7,
            schema="ABAB",
            success_criteria_ru="Нет дней с strain >= 14 при recovery < 50; "
                                 "среднее recovery в фазе B выше A на >= 5 пунктов.",
        )

    if kind == "weekend_pattern":
        return Protocol(
            id="protocol-weekend_pattern",
            hypothesis_ru="Выравнивание времени отбоя в выходные убирает просадку recovery.",
            intervention_ru="В выходные держите будний отбой (в пределах 30 минут).",
            metric="recovery",
            baseline_days=14,
            intervention_days=14,
            schema="ABAB",
            success_criteria_ru="Разница среднего recovery будни-выходные становится < 5 пунктов.",
        )

    if kind == "sleep_consistency":
        return Protocol(
            id="protocol-sleep_consistency",
            hypothesis_ru="Стабильное время сна важнее идеальной длительности и поднимает восстановление.",
            intervention_ru="Фиксируйте время подъёма (в пределах 30 минут) 14 дней, включая выходные.",
            metric="sleep_h",
            baseline_days=14,
            intervention_days=14,
            schema="AB",
            success_criteria_ru="Стандартное отклонение длительности сна < 1.0ч; "
                                 "среднее recovery выше на >= 5 пунктов.",
        )

    return None


# --- from a personal correlation ---------------------------------------------

def from_correlation(corr: Dict[str, Any]) -> Optional[Protocol]:
    """Build an ABAB verification protocol from a C2+ correlation insight.

    ``corr`` is a correlations-module insight dict (see
    ``openhealth.modules.correlations``): it carries ``metadata`` with
    ``behavior_id``, ``impact``, ``direction`` and ``confidence_grade``.
    """
    meta = corr.get("metadata", {})
    bid = meta.get("behavior_id") or "behavior"
    name = (corr.get("title", "") or "").replace("Impact: ", "").strip() or bid
    impact = abs(float(meta.get("impact", 0.0)))
    direction = meta.get("direction", "positive")

    if direction == "positive":
        intervention = "Сознательно выполняйте '%s' каждый день фазы вмешательства." % name
        crit = ("Среднее recovery в фазах с '%s' выше, чем без него, на >= %s пунктов."
                % (name, _round_points(impact)))
        hypo = "Если регулярно делать '%s', восстановление вырастет." % name
    else:
        intervention = "Уберите '%s' на время фазы вмешательства." % name
        crit = ("Среднее recovery в фазах без '%s' выше, чем с ним, на >= %s пунктов."
                % (name, _round_points(impact)))
        hypo = "Если убрать '%s', восстановление вырастет." % name

    return Protocol(
        id="protocol-corr-%s" % bid,
        hypothesis_ru=hypo,
        intervention_ru=intervention,
        metric="recovery",
        baseline_days=7,
        intervention_days=7,
        schema="ABAB",
        success_criteria_ru=crit,
    )


def _round_points(x: float) -> str:
    # At least a 3-point bar so the test is not chasing noise.
    return "%d" % max(3, round(x))


# --- orchestration ------------------------------------------------------------

def build_protocols(
    insights: List["insights_mod.Insight"],
    correlations: Optional[List[Dict[str, Any]]] = None,
) -> List[Protocol]:
    """Build up to 3 active protocol suggestions, highest severity first.

    Insight-derived protocols are ranked by the severity and confidence of the
    insight; correlation-derived protocols slot in at "attention" weight, ranked
    by their confidence grade. Returns at most ``MAX_ACTIVE_PROTOCOLS``.
    """
    ranked: List[tuple] = []  # (severity_rank, -confidence, seq, protocol)
    seq = 0

    for ins in insights or []:
        proto = from_insight(ins, correlations=correlations)
        if proto is None:
            continue
        sev_rank = insights_mod._SEVERITY_RANK.get(ins.severity, 9)
        conf = evidence.confidence_to_numeric(ins.confidence)
        ranked.append((sev_rank, -conf, seq, proto))
        seq += 1

    seen_bids = set()
    for corr in correlations or []:
        meta = corr.get("metadata", {})
        grade = meta.get("confidence_grade", "C1")
        # Only C2 and above are worth a verification protocol.
        if grade in ("C1",):
            continue
        bid = meta.get("behavior_id")
        if bid in seen_bids:
            continue
        seen_bids.add(bid)
        proto = from_correlation(corr)
        if proto is None:
            continue
        conf = evidence.confidence_to_numeric(evidence.Confidence(grade))
        ranked.append((insights_mod._SEVERITY_RANK[insights_mod.ATTENTION], -conf, seq, proto))
        seq += 1

    ranked.sort(key=lambda t: (t[0], t[1], t[2]))
    return [t[3] for t in ranked[:MAX_ACTIVE_PROTOCOLS]]


def protocols_to_dicts(protocols: List[Protocol]) -> List[Dict[str, Any]]:
    """Convenience: serialize protocols for JSON / the dashboard."""
    return [p.to_dict() for p in protocols]
