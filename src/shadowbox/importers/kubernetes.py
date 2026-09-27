"""Import Kubernetes manifests into a ShadowBox model (workloads only).

Workloads (Deployment, StatefulSet, DaemonSet, Job) become components with
estimated defaults. Connections come ONLY from the explicit annotation
`shadowbox.io/depends-on: "a, b"` on the workload metadata — env-var
sniffing is guesswork and stays out. Services, ConfigMaps, and the rest
are ignored with a warning count.
"""

from pathlib import Path
from typing import Any

import yaml

from shadowbox.errors import SchemaError, UnsafeYamlError
from shadowbox.importers.compose import _infer_type, skeleton
from shadowbox.model import SystemModel

WORKLOAD_KINDS = {"Deployment", "StatefulSet", "DaemonSet", "Job", "ReplicaSet"}
DEPENDS_ANNOTATION = "shadowbox.io/depends-on"


def _containers(doc: dict[str, Any]) -> list[dict[str, Any]]:
    spec = doc.get("spec", {})
    if not isinstance(spec, dict):
        return []
    template = spec.get("template", {}).get("spec", {}) if "template" in spec else spec
    containers = template.get("containers", []) if isinstance(template, dict) else []
    return [c for c in containers if isinstance(c, dict)]


def _image(doc: dict[str, Any]) -> str:
    containers = _containers(doc)
    return str(containers[0].get("image", "")) if containers else ""


def _depends(doc: dict[str, Any]) -> list[str]:
    metadata = doc.get("metadata", {})
    annotations = metadata.get("annotations", {}) if isinstance(metadata, dict) else {}
    raw = annotations.get(DEPENDS_ANNOTATION, "") if isinstance(annotations, dict) else ""
    return sorted(part.strip() for part in str(raw).split(",") if part.strip())


def import_kubernetes(path: Path) -> tuple[SystemModel, list[str]]:
    """Parse manifests; returns (model, warnings). All metrics are estimates."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc
    if "!!python/" in raw_text or "!python/" in raw_text:
        raise UnsafeYamlError(f"{path}: unsafe YAML tag rejected")
    try:
        docs = [d for d in yaml.safe_load_all(raw_text) if isinstance(d, dict)]
    except yaml.YAMLError as exc:
        raise SchemaError(f"{path}: invalid YAML: {exc}") from exc
    if not docs:
        raise SchemaError(f"{path}: no Kubernetes documents found")
    components: list[dict[str, Any]] = []
    connections: list[dict[str, Any]] = []
    warnings: list[str] = []
    ignored = 0
    for doc in sorted(docs, key=lambda d: str(d.get("metadata", {}).get("name", ""))):
        kind = str(doc.get("kind", ""))
        name = str(doc.get("metadata", {}).get("name", ""))
        if kind not in WORKLOAD_KINDS or not name:
            ignored += 1
            continue
        image = _image(doc)
        component_type = _infer_type(name, image)
        components.append(skeleton(name, component_type))
        shown = image if image else "(no image)"
        warnings.append(f"{name!r}: {component_type} from {kind} {shown}; estimated")
        for dep in _depends(doc):
            connections.append({"from": name, "to": dep})
    if not components:
        raise SchemaError(f"{path}: no workloads found (need one of {sorted(WORKLOAD_KINDS)})")
    if ignored:
        warnings.append(f"ignored {ignored} non-workload document(s)")
    known = {c["id"] for c in components}
    kept = []
    for conn in connections:
        if conn["to"] not in known:
            warnings.append(f"dropped {conn['from']} -> {conn['to']} (unknown)")
            continue
        kept.append(conn)
    for conn in kept:
        warnings.append(f"edge {conn['from']!r} -> {conn['to']!r} from {DEPENDS_ANNOTATION}")
    try:
        model = SystemModel.model_validate({"components": components, "connections": kept})
    except Exception as exc:
        raise SchemaError(f"{path}: cannot build model: {exc}") from exc
    return (model, warnings)
