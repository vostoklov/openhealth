"""Module contract + registry. Pure stdlib, zero external deps (core rule)."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Protocol, runtime_checkable


@dataclass
class ModuleResult:
    """What a module returns from compute().

    `metrics` and `insights` are plain dicts shaped like the canonical records
    in `openhealth.models` (Observation / InsightHypothesis / PatternAlert), so
    they flow into the same index, contexts and agent responses.
    """

    metrics: List[Dict[str, Any]] = field(default_factory=list)
    insights: List[Dict[str, Any]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)


@runtime_checkable
class HealthModule(Protocol):
    id: str          # stable slug, e.g. "pulse"
    name: str        # human label, e.g. "Pulse — HRV & readiness"
    domain: str      # one of the known domains
    summary: str     # one line for the agent to describe the module

    def schema(self) -> Dict[str, Any]:
        """JSON Schema for this module's compute() payload."""
        ...

    def compute(self, payload: Dict[str, Any]) -> ModuleResult:
        """Pure function: payload -> evidence-graded metrics + cautious insights."""
        ...


KNOWN_DOMAINS = (
    "pulse",         # HRV / heart / stress / energy / readiness
    "cycle",         # menstrual cycle / fertility
    "body",          # weight / fasting / habits
    "metabolic",     # nutrition / glucose
    "skin",          # face / skin photo observations
    "sleep",         # sleep stages proxy / circadian / light
    "journal",       # daily behavior check-ins (WHOOP-style journal)
    "recovery",      # versioned recovery / strain / sleep-debt scoring
    "correlations",  # behavior <-> recovery personal impact analysis
    "medications",   # medication / supplement / habit intervention ledger
    "nutrition",     # eating-style profile + meal journal
)


_REGISTRY: Dict[str, "HealthModule"] = {}


def register(module: "HealthModule") -> None:
    if not getattr(module, "id", None):
        raise ValueError("module must have a non-empty id")
    if module.domain not in KNOWN_DOMAINS:
        raise ValueError(
            "unknown domain %r; add it to KNOWN_DOMAINS first" % module.domain
        )
    _REGISTRY[module.id] = module


def get_module(module_id: str) -> "HealthModule":
    if module_id not in _REGISTRY:
        raise KeyError("no module registered with id %r" % module_id)
    return _REGISTRY[module_id]


def all_modules() -> List["HealthModule"]:
    return sorted(_REGISTRY.values(), key=lambda m: m.id)
