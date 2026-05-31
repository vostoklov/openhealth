"""Domain module system for OpenHealth.

OpenHealth is agent-native: a person interacts through Claude Code / Codex, and
each health domain (pulse, cycle, body, metabolic, skin, sleep) is a self-
contained *module* plugin. A module declares its input JSON Schema and a pure
`compute()` that turns a payload into evidence-graded metrics and cautious
insights. Modules never diagnose; they reuse the C1-C5 confidence scale and
red-flag checks from `openhealth.evidence`.

Adding a domain = adding a module that registers itself here. A newcomer (via an
agent) copies an existing module, fills in `schema()` and `compute()`, and the
registry picks it up — no core changes required.
"""

from .base import HealthModule, ModuleResult, register, get_module, all_modules


def load_builtin() -> None:
    """Import built-in modules so they self-register. Safe to call repeatedly."""
    from . import pulse  # noqa: F401  (import side-effect: registration)
    from . import sleep  # noqa: F401
    from . import cycle  # noqa: F401
    from . import body   # noqa: F401


__all__ = [
    "HealthModule",
    "ModuleResult",
    "register",
    "get_module",
    "all_modules",
    "load_builtin",
]
