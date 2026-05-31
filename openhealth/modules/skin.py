"""Skin module — summarize photo/skin observations by body zone over time.

Reuses the existing BodyZone / visible-attribute vocabulary. From a set of dated
observations it counts attributes per zone and surfaces a gentle "this keeps
showing up" prompt — never a diagnosis. Pure stdlib.
"""

from typing import Any, Dict, List

from .base import ModuleResult, register
from .. import evidence
from ..models import BodyZone


def _valid_zone(zone: str) -> str:
    valid = {z.value for z in BodyZone}
    return zone if zone in valid else "custom"


def summarize(observations: List[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    """Per-zone attribute counts across the observation set."""
    out: Dict[str, Dict[str, int]] = {}
    for o in observations:
        zone = _valid_zone(o.get("body_zone", "custom"))
        bucket = out.setdefault(zone, {})
        for attr in o.get("visible_attributes", []) or []:
            bucket[attr] = bucket.get(attr, 0) + 1
    return out


class SkinModule:
    id = "skin"
    name = "Skin — zone observations over time"
    domain = "skin"
    summary = "Counts visible-attribute observations per body zone and flags persistent ones (no diagnosis)."

    def schema(self) -> Dict[str, Any]:
        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "title": "SkinInput",
            "type": "object",
            "required": ["observations"],
            "properties": {
                "observations": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "required": ["body_zone"],
                        "properties": {
                            "date": {"type": "string"},
                            "body_zone": {"type": "string"},
                            "visible_attributes": {"type": "array", "items": {"type": "string"}},
                            "severity": {"type": "string"},
                        },
                    },
                }
            },
        }

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        obs = payload.get("observations", [])
        if not obs:
            raise ValueError("need at least one observation")
        per_zone = summarize(obs)

        metrics: List[Dict[str, Any]] = [{
            "id": "obs-skin-summary",
            "record_type": "Observation",
            "source_id": "skin",
            "title": "Skin observations by zone",
            "summary": "%d observation(s) across %d zone(s)." % (len(obs), len(per_zone)),
            "artifact_ids": [],
            "evidence_class": "personal",
            "confidence": 0.85,
            "tags": ["skin"],
            "metadata": {"per_zone": per_zone, "n": len(obs)},
            "observation_kind": "skin_summary",
            "metric_name": "skin_observations",
            "value": len(obs),
            "unit": "count",
        }]

        insights: List[Dict[str, Any]] = []
        for zone, attrs in per_zone.items():
            for attr, count in attrs.items():
                if count >= 3:
                    conf = evidence.Confidence.C2
                    txt = ("'%s' on the %s zone shows up %d times in this set. "
                           "If it persists or worsens, consider a clinician." % (attr, zone, count))
                    insights.append({
                        "id": "insight-skin-%s-%s" % (zone, attr),
                        "record_type": "InsightHypothesis",
                        "source_id": "skin",
                        "title": "Recurring skin observation",
                        "summary": evidence.frame_statement(txt, conf),
                        "artifact_ids": [],
                        "evidence_class": "derived-hypothesis",
                        "confidence": evidence.confidence_to_numeric(conf),
                        "tags": ["skin", "review-needed"],
                        "metadata": {"zone": zone, "attribute": attr, "count": count},
                        "statement": txt,
                        "evidence_record_ids": ["obs-skin-summary"],
                        "open_questions": ["Did anything change in routine/products/diet?"],
                    })

        return ModuleResult(metrics=metrics, insights=insights)


register(SkinModule())
