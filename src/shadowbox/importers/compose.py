"""Import a docker-compose file into a ShadowBox model (M2).

Every performance field is an estimated default, never a measurement:
the caller must calibrate before trusting any simulation output.
"""

from pathlib import Path
from typing import Any

import yaml

from shadowbox.errors import SchemaError, UnsafeYamlError
from shadowbox.model import SystemModel

_DB_HINTS = ("postgres", "mysql", "mariadb", "mongo", "sqlite", "cockroach", "cassandra")
_CACHE_HINTS = ("redis", "memcached", "valkey", "cache")

_DEFAULTS: dict[str, dict[str, Any]] = {
    "service": {
        "capacity": 20,
        "latency_ms": {"base": 20, "jitter_ms": 5},
        "timeout_ms": 1000,
        "queue_size": 100,
        "queue_policy": "drop",
    },
    "database": {
        "capacity": 10,
        "latency_ms": {"base": 5, "jitter_ms": 1},
        "timeout_ms": 500,
        "queue_size": 50,
        "queue_policy": "fifo",
    },
    "cache": {
        "capacity": 50,
        "latency_ms": {"base": 2, "jitter_ms": 1},
        "timeout_ms": 200,
        "queue_size": 200,
        "queue_policy": "drop",
    },
}


def _infer_type(service: str, image: str) -> str:
    lowered = image.lower()
    if any(hint in lowered for hint in _DB_HINTS):
        return "database"
    if any(hint in lowered for hint in _CACHE_HINTS):
        return "cache"
    return "service"


def _depends_on(spec: Any) -> list[str]:
    if spec is None:
        return []
    if isinstance(spec, list):
        return [str(item) for item in spec]
    if isinstance(spec, dict):
        return sorted(str(key) for key in spec)
    return []


def _links(spec: Any) -> list[str]:
    if not isinstance(spec, list):
        return []
    return [str(item).split(":")[0] for item in spec]


def import_compose(path: Path) -> tuple[SystemModel, list[str]]:
    """Parse compose file; returns (model, warnings). All metrics are estimates."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc
    if "!!python/" in raw_text or "!python/" in raw_text:
        raise UnsafeYamlError(f"{path}: unsafe YAML tag rejected")
    try:
        data = yaml.safe_load(raw_text)
    except yaml.YAMLError as exc:
        raise SchemaError(f"{path}: invalid YAML: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("services"), dict):
        raise SchemaError(f"{path}: top-level `services` mapping required")
    services: dict[str, Any] = data["services"]
    if not services:
        raise SchemaError(f"{path}: no services defined")
    components: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    warnings: list[str] = []
    for name in sorted(services):
        spec = services[name] if isinstance(services[name], dict) else {}
        image = str(spec.get("image", ""))
        kind = _infer_type(name, image)
        fields = dict(_DEFAULTS[kind])
        components.append({"id": name, "type": kind, **fields})
        shown_image = image if image else "(none)"
        warnings.append(f"{name!r}: {kind} inferred from {shown_image}; fields estimated")
        for dep in sorted(set(_depends_on(spec.get("depends_on")) + _links(spec.get("links")))):
            connections.append({"from": name, "to": dep})
    known_names = set(services)
    kept: list[dict[str, Any]] = []
    for conn in connections:
        if conn["to"] not in known_names:
            warnings.append(f"dropped {conn['from']} -> {conn['to']} (outside compose)")
            continue
        kept.append(conn)
    try:
        model = SystemModel.model_validate({"components": components, "connections": kept})
    except Exception as exc:
        raise SchemaError(f"{path}: cannot build model: {exc}") from exc
    return (model, warnings)
