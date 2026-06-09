"""Provider catalog: which devices/services OpenHealth can talk to, and how.

The catalog itself lives as a static JSON resource in ``openhealth/data/
providers.json`` — an Open Wearables-style registry of direct-API integrations.
For every provider it records where the developer portal lives, the concrete
steps to mint credentials, what data the API serves, and an honest ``status``:

* ``supported``   — a connector ships in this repo today
* ``planned``     — a real, self-serve API exists; connector not written yet
* ``export_only`` — no official open API; file export or a local bridge is the
  honest route (never pretend an API exists when it does not)

Compiled clean-room from public developer documentation only. Pure stdlib,
zero external deps (core rule). The JSON is cached after the first read so
repeated calls stay cheap.

Typical use from UI/CLI code::

    from openhealth import providers
    cat = providers.load_providers()          # list of provider dicts
    whoop = providers.get_provider("whoop")   # one provider or None
    problems = providers.validate_catalog()   # [] when the catalog is sound
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# data/providers.json sits next to this module.
_RESOURCE_PATH = Path(__file__).resolve().parent / "data" / "providers.json"

_CACHE: Optional[Dict[str, Any]] = None

CATEGORIES = ("tracker", "scale", "cgm", "air", "sleep", "bp", "hub")
AUTH_KINDS = ("oauth2", "pat", "api_key", "file_export", "local")
STATUSES = ("supported", "planned", "export_only")

# Every provider entry must carry these keys (value may be null where noted in
# the JSON itself, e.g. api_base for export-only providers).
REQUIRED_FIELDS = (
    "id",
    "label",
    "category",
    "auth",
    "status",
    "api_base",
    "dev_portal_url",
    "docs_url",
    "key_steps",
    "data_types",
    "rate_limit_note",
    "connector",
    "env_vars",
)

_ID_RE = re.compile(r"^[a-z0-9_]+$")


def _load(force_reload: bool = False) -> Dict[str, Any]:
    global _CACHE
    if _CACHE is None or force_reload:
        _CACHE = json.loads(_RESOURCE_PATH.read_text(encoding="utf-8"))
    return _CACHE


def catalog(force_reload: bool = False) -> Dict[str, Any]:
    """Return the whole catalog payload (version, updated, providers)."""
    return _load(force_reload=force_reload)


def load_providers(force_reload: bool = False) -> List[Dict[str, Any]]:
    """Flat list of every provider entry in the catalog."""
    return list(_load(force_reload=force_reload)["providers"])


def get_provider(provider_id: str) -> Optional[Dict[str, Any]]:
    """Look up a single provider by its ``id``. Returns None when unknown."""
    wanted = (provider_id or "").strip().lower()
    for entry in load_providers():
        if entry["id"] == wanted:
            return entry
    return None


def by_category(category: str) -> List[Dict[str, Any]]:
    """All providers in one category (``tracker``, ``cgm``, ``air``, ...)."""
    return [p for p in load_providers() if p.get("category") == category]


def by_status(status: str) -> List[Dict[str, Any]]:
    """All providers with one status (``supported``/``planned``/``export_only``)."""
    return [p for p in load_providers() if p.get("status") == status]


def summary() -> Dict[str, Any]:
    """Compact counts for UI/CLI: totals by category and by status."""
    entries = load_providers()
    by_cat: Dict[str, int] = {}
    by_stat: Dict[str, int] = {}
    for entry in entries:
        by_cat[entry["category"]] = by_cat.get(entry["category"], 0) + 1
        by_stat[entry["status"]] = by_stat.get(entry["status"], 0) + 1
    return {
        "total": len(entries),
        "by_category": by_cat,
        "by_status": by_stat,
        "supported_ids": [p["id"] for p in entries if p["status"] == "supported"],
    }


def _check_url(problems: List[str], pid: str, field: str, value: Any) -> None:
    if value is None:
        return
    if not isinstance(value, str) or not value.startswith("https://"):
        problems.append("%s: %s must be an https:// URL or null, got %r" % (pid, field, value))


def validate_catalog(payload: Optional[Dict[str, Any]] = None) -> List[str]:
    """Schema-check the catalog. Returns a list of problems; empty == valid.

    Checks: top-level shape, required fields, enum membership, unique ids,
    https URLs (dev portal / docs), non-trivial key_steps for supported
    providers, and list-typed step/data/env fields.
    """
    payload = payload if payload is not None else _load()
    problems: List[str] = []

    if not isinstance(payload, dict):
        return ["catalog payload must be an object"]
    if not isinstance(payload.get("version"), int):
        problems.append("catalog: 'version' must be an integer")
    entries = payload.get("providers")
    if not isinstance(entries, list) or not entries:
        problems.append("catalog: 'providers' must be a non-empty list")
        return problems

    seen_ids: set = set()
    for raw in entries:
        if not isinstance(raw, dict):
            problems.append("provider entries must be objects, got %r" % type(raw).__name__)
            continue
        pid = raw.get("id", "<missing id>")

        for field in REQUIRED_FIELDS:
            if field not in raw:
                problems.append("%s: missing required field '%s'" % (pid, field))

        if not isinstance(pid, str) or not _ID_RE.match(pid or ""):
            problems.append("%s: id must match %s" % (pid, _ID_RE.pattern))
        if pid in seen_ids:
            problems.append("%s: duplicate provider id" % pid)
        seen_ids.add(pid)

        if not isinstance(raw.get("label"), str) or not raw.get("label", "").strip():
            problems.append("%s: label must be a non-empty string" % pid)
        if raw.get("category") not in CATEGORIES:
            problems.append("%s: category %r not in %s" % (pid, raw.get("category"), list(CATEGORIES)))
        if raw.get("auth") not in AUTH_KINDS:
            problems.append("%s: auth %r not in %s" % (pid, raw.get("auth"), list(AUTH_KINDS)))
        if raw.get("status") not in STATUSES:
            problems.append("%s: status %r not in %s" % (pid, raw.get("status"), list(STATUSES)))

        _check_url(problems, pid, "dev_portal_url", raw.get("dev_portal_url"))
        _check_url(problems, pid, "docs_url", raw.get("docs_url"))
        api_base = raw.get("api_base")
        if api_base is not None and (not isinstance(api_base, str) or not api_base.startswith("http")):
            # Local bridges (Home Assistant) may legitimately be plain-http on
            # the LAN; everything else in the catalog is https.
            problems.append("%s: api_base must be an http(s) URL or null" % pid)

        key_steps = raw.get("key_steps")
        steps_ok = isinstance(key_steps, list) and bool(key_steps) and all(
            isinstance(s, str) and s.strip() for s in key_steps
        )
        if not steps_ok:
            problems.append("%s: key_steps must be a list of non-empty strings" % pid)
        elif raw.get("status") == "supported" and len(key_steps) < 2:
            problems.append("%s: supported providers need at least 2 key_steps" % pid)

        data_types = raw.get("data_types")
        if not isinstance(data_types, list) or not data_types or not all(isinstance(d, str) for d in data_types):
            problems.append("%s: data_types must be a non-empty list of strings" % pid)

        if not isinstance(raw.get("rate_limit_note"), str) or not raw.get("rate_limit_note", "").strip():
            problems.append("%s: rate_limit_note must be a non-empty string" % pid)

        env_vars = raw.get("env_vars")
        if not isinstance(env_vars, list) or not all(isinstance(v, str) for v in env_vars):
            problems.append("%s: env_vars must be a list of strings" % pid)

        connector = raw.get("connector")
        if connector is not None and not isinstance(connector, str):
            problems.append("%s: connector must be a string path or null" % pid)
        if raw.get("status") == "supported" and not connector:
            problems.append("%s: supported providers must reference their connector" % pid)

    return problems
