"""Safe YAML loading + structural validation for M0 (no engine)."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from shadowbox.errors import (
    CycleError,
    RefError,
    SchemaError,
    TooLargeError,
    UnsafeYamlError,
)
from shadowbox.model import MAX_COMPONENTS, Scenario, SystemModel

_UNSAFE_TAGS = ("!!python/", "!python/")


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SchemaError(f"cannot read {path}: {exc}") from exc


def _safe_load_yaml(path: Path) -> Any:
    raw = _read_text(path)
    for tag in _UNSAFE_TAGS:
        if tag in raw:
            raise UnsafeYamlError(f"{path}: unsafe YAML tag {tag!r} rejected")
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise SchemaError(f"{path}: invalid YAML: {exc}") from exc


def _check_cycles(model: SystemModel) -> None:
    adjacency: dict[str, list[str]] = {c.id: [] for c in model.components}
    for conn in model.connections:
        adjacency[conn.from_].append(conn.to)
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node: str, stack: list[str]) -> None:
        if node in visiting:
            raise CycleError(f"cycle detected: {' -> '.join([*stack, node])}")
        if node in visited:
            return
        visiting.add(node)
        for nxt in sorted(adjacency[node]):
            visit(nxt, [*stack, node])
        visiting.remove(node)
        visited.add(node)

    for node in sorted(adjacency):
        visit(node, [])


def load_model(path: Path) -> SystemModel:
    data = _safe_load_yaml(path)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: top-level mapping required")
    try:
        model = SystemModel.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(f"{path}: {exc}") from exc
    if len(model.components) > MAX_COMPONENTS:
        raise TooLargeError(f"{path}: {len(model.components)} components > {MAX_COMPONENTS}")
    known = {c.id for c in model.components}
    for conn in model.connections:
        if conn.from_ not in known or conn.to not in known:
            raise RefError(f"{path}: unknown connection endpoint {conn.from_!r} -> {conn.to!r}")
    _check_cycles(model)
    return model


def load_scenario(path: Path, model: SystemModel) -> Scenario:
    data = _safe_load_yaml(path)
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: top-level mapping required")
    payload = data.get("scenario", data)
    try:
        scenario = Scenario.model_validate(payload)
    except ValidationError as exc:
        raise SchemaError(f"{path}: {exc}") from exc
    known = {c.id for c in model.components}
    for fault in scenario.faults:
        if fault.target not in known:
            raise RefError(f"{path}: unknown fault target {fault.target!r}")
        if fault.start_s + fault.duration_s > scenario.duration_s:
            raise SchemaError(f"{path}: fault exceeds scenario duration")
    return scenario
