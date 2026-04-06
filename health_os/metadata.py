import json
from pathlib import Path
from typing import Any, Dict, List


def _coerce_value(raw: str) -> Any:
    value = raw.strip()
    if not value:
        return ""
    if value.startswith("[") or value.startswith("{"):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if "," in value:
        return [item.strip() for item in value.split(",") if item.strip()]
    if value.lower() in {"true", "false"}:
        return value.lower() == "true"
    return value


def parse_frontmatter(text: str) -> Dict[str, Any]:
    if not text.startswith("---\n"):
        return {}
    end_marker = text.find("\n---", 4)
    if end_marker == -1:
        return {}
    raw = text[4:end_marker]
    payload: Dict[str, Any] = {}
    for line in raw.splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        payload[key.strip()] = _coerce_value(value)
    return payload


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    end_marker = text.find("\n---", 4)
    if end_marker == -1:
        return text
    return text[end_marker + 4 :].lstrip("\n")


def load_sidecar_metadata(path: Path) -> Dict[str, Any]:
    sidecar = path.with_name(path.name + ".meta.json")
    if not sidecar.exists():
        return {}
    return json.loads(sidecar.read_text(encoding="utf-8"))


def coerce_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    return [str(value)]
