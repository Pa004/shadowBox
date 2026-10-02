"""Model calibration against measured medians (evidence-grounded, no magic).

Method: for each measured component, factor = measured_p50 / current base.
The factor scales `latency_ms.base` (jitter untouched). This assumes the
measurements are low-load service-time medians; queueing and contention
still come from the engine, not from this file.

fit_error = max over components of |factor - 1|, i.e. how far the prior
estimates were from measurement. Rule: fit_error <= 15% -> "medium",
otherwise "low" with the error exposed. "medium" therefore means
"parameters within 15% of measured medians" — never "predictions validated".
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from shadowbox.errors import RefError, SchemaError, UnsafeYamlError
from shadowbox.model import SystemModel
from shadowbox.report import FIT_LIMIT

WARN_FACTOR_LOW = 0.5
WARN_FACTOR_HIGH = 2.0


class ComponentMeasurement(BaseModel):
    p50: float = Field(gt=0)


class Measurements(BaseModel):
    source: str = Field(min_length=1)
    measured_at: str = Field(min_length=1)
    components: dict[str, ComponentMeasurement] = Field(min_length=1)


def _read_measurements(path: Path) -> Measurements:
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
    if not isinstance(data, dict):
        raise SchemaError(f"{path}: top-level mapping required")
    try:
        return Measurements.model_validate(data)
    except ValidationError as exc:
        raise SchemaError(f"{path}: {exc}") from exc


def calibrate(model: SystemModel, measurements: Measurements) -> tuple[SystemModel, dict[str, Any]]:
    """Return (calibrated model, calibration record). Raises on unknown targets."""
    known = {c.id: c for c in model.components}
    unknown = sorted(set(measurements.components) - set(known))
    if unknown:
        raise RefError(f"unknown measurement targets: {', '.join(unknown)}")
    factors: dict[str, float] = {}
    warned: list[str] = []
    for cid, measured in measurements.components.items():
        base = known[cid].latency_ms.base
        if base <= 0:
            raise SchemaError(f"component {cid!r} has non-positive base latency; cannot scale")
        factor = measured.p50 / base
        factors[cid] = factor
        if not WARN_FACTOR_LOW <= factor <= WARN_FACTOR_HIGH:
            warned.append(f"{cid}: factor {factor:.2f} outside sane range — verify measurements")
    data = model.model_dump(mode="json", by_alias=True)
    for comp in data["components"]:
        if comp["id"] in factors:
            scaled = comp["latency_ms"]["base"] * factors[comp["id"]]
            comp["latency_ms"]["base"] = max(1, round(scaled))
    fit_error = max(abs(f - 1.0) for f in factors.values())
    record = {
        "source": measurements.source,
        "measured_at": measurements.measured_at,
        "factors": {k: round(v, 4) for k, v in sorted(factors.items())},
        "fit_error": round(fit_error, 4),
        "fit_limit": FIT_LIMIT,
        "model_confidence": "medium" if fit_error <= FIT_LIMIT else "low",
        "warnings": sorted(warned),
    }
    data["metadata"] = {**(data.get("metadata") or {}), "calibration": record}
    return (SystemModel.model_validate(data), record)


def calibrate_file(model_path: Path, measurements_path: Path) -> tuple[SystemModel, dict[str, Any]]:
    """Load, validate refs, and calibrate. Model validation errors surface as-is."""
    from shadowbox.dsl import load_model

    model = load_model(model_path)
    return calibrate(model, _read_measurements(measurements_path))
