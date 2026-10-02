"""Model calibration v2: latency, capacity, and queues from measurements.

Evidence per parameter (no parameter moves without its own):
- latency base <- low-load service-time p50 per component (direct ratio).
- capacity <- per-component saturation throughput measured in isolation:
  expected_sat = capacity / mean_service_s, so factor = measured / expected.
- queue_size <- per-component max observed queue under the reference
  workload: factor = measured / simulated (simulated comes from the engine
  with latency+capacity already applied, so no circularity).

Order per pass: latency, capacity, queues. Queues depend on simulation,
so passes repeat (max 3) until the largest parameter change is < 1%;
otherwise the record says so and confidence stays low.

Agreement rule (replaces prior-surprise as the gate): the final model
re-simulates the reference workload and must match observed aggregates —
p50 within 15%, error_rate within 2pp, throughput within 10%. "medium"
means "agrees with measurement under these tolerances", never more.
"""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from shadowbox.engine import MAX_REQUESTS, simulate
from shadowbox.errors import RefError, SchemaError, UnsafeYamlError
from shadowbox.metrics import summarize
from shadowbox.model import Component, Scenario, SystemModel, Workload
from shadowbox.report import FIT_LIMIT

WARN_FACTOR_LOW = 0.5
WARN_FACTOR_HIGH = 2.0
MAX_PASSES = 3
CONVERGE_TOL = 0.01
QUEUE_SEARCH_ITERS = 6
QUEUE_CAP = 10000
AGREE_P50 = 0.15
AGREE_ERROR_PP = 0.02
AGREE_TPS = 0.10
PROBE_SEED = 0


class Reference(BaseModel):
    rate_rps: int = Field(default=50, gt=0)
    duration_s: int = Field(default=10, gt=0)
    seed: int = Field(default=0)
    observed: dict[str, float] = Field(default_factory=dict)


class ComponentMeasurement(BaseModel):
    p50: float | None = Field(default=None, gt=0)
    sat_tps: float | None = Field(default=None, gt=0)
    queue_max: int | None = Field(default=None, gt=0)


class Measurements(BaseModel):
    source: str = Field(min_length=1)
    measured_at: str = Field(min_length=1)
    reference: Reference = Field(default_factory=Reference)
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


def _check_targets(model: SystemModel, measurements: Measurements) -> dict[str, Component]:
    known = {c.id: c for c in model.components}
    unknown = sorted(set(measurements.components) - set(known))
    if unknown:
        raise RefError(f"unknown measurement targets: {', '.join(unknown)}")
    return known


def _warn(factor: float, cid: str, warned: list[str]) -> None:
    if not WARN_FACTOR_LOW <= factor <= WARN_FACTOR_HIGH:
        warned.append(f"{cid}: factor {factor:.2f} outside sane range — verify measurements")


def _mean_service_s(comp: Component) -> float:
    return (comp.latency_ms.base + comp.latency_ms.jitter_ms / 2) / 1000


def _latency_factors(
    known: dict[str, Component], measurements: Measurements, warned: list[str]
) -> dict[str, float]:
    factors = {}
    for cid, measured in measurements.components.items():
        if measured.p50 is None:
            continue
        base = known[cid].latency_ms.base
        if base <= 0:
            raise SchemaError(f"component {cid!r} has non-positive base latency; cannot scale")
        factor = measured.p50 / base
        factors[cid] = factor
        _warn(factor, cid, warned)
    return factors


def _capacity_factors(
    known: dict[str, Component], measurements: Measurements, warned: list[str]
) -> dict[str, float]:
    factors = {}
    for cid, measured in measurements.components.items():
        if measured.sat_tps is None:
            continue
        expected = known[cid].capacity / _mean_service_s(known[cid])
        factor = measured.sat_tps / expected
        factors[cid] = factor
        _warn(factor, cid, warned)
    return factors


def _apply_factors(data: dict[str, Any], factors: dict[str, float], field: str) -> None:
    for comp in data["components"]:
        if comp["id"] not in factors:
            continue
        if field == "base":
            value = comp["latency_ms"]["base"] * factors[comp["id"]]
            comp["latency_ms"]["base"] = max(1, round(value))
        elif field == "capacity":
            factor = min(10.0, max(0.1, factors[comp["id"]]))
            comp["capacity"] = max(1, round(comp["capacity"] * factor))
        else:
            value = comp["queue_size"] * factors[comp["id"]]
            comp["queue_size"] = min(QUEUE_CAP, max(1, round(value)))


def _reference_scenario(measurements: Measurements) -> Scenario:
    ref = measurements.reference
    total = ref.rate_rps * ref.duration_s
    if total > MAX_REQUESTS:
        raise SchemaError(f"reference workload {total} requests exceeds cap {MAX_REQUESTS}")
    return Scenario(
        name="calibration-reference",
        duration_s=ref.duration_s,
        workload=Workload(rate_rps=ref.rate_rps),
    )


def _simulate(model: SystemModel, scenario: Scenario, seed: int) -> tuple[dict[str, Any], Any]:
    result = simulate(model, scenario, seed)
    return summarize(model, result, scenario.duration_s), result


def _queue_factors(
    model: SystemModel, measurements: Measurements, warned: list[str]
) -> dict[str, float]:
    wanted = {
        cid: m.queue_max for cid, m in measurements.components.items() if m.queue_max is not None
    }
    if not wanted:
        return {}
    scenario = _reference_scenario(measurements)
    factors = {cid: 1.0 for cid in wanted}
    for _ in range(QUEUE_SEARCH_ITERS):
        metrics, _ = _simulate(model, scenario, measurements.reference.seed)
        depths = {cid: metrics["components"][cid]["queue_depth"] for cid in wanted}
        done = True
        for cid, target in wanted.items():
            current = max(1, depths[cid])
            if current == 0 or abs(current - target) / target < 0.5:
                continue
            done = False
            factors[cid] = max(0.1, factors[cid] * target / current)
        if done:
            break
        model = _rebuild(model, {}, {}, factors)
    return factors


def _rebuild(
    model: SystemModel,
    latency: dict[str, float],
    capacity: dict[str, float],
    queues: dict[str, float],
) -> SystemModel:
    data = model.model_dump(mode="json", by_alias=True)
    _apply_factors(data, latency, "base")
    _apply_factors(data, capacity, "capacity")
    _apply_factors(data, queues, "queue_size")
    return SystemModel.model_validate(data)


def _agreement(
    model: SystemModel, measurements: Measurements
) -> tuple[list[dict[str, Any]], bool]:
    observed = measurements.reference.observed
    if not observed:
        return ([], True)
    scenario = _reference_scenario(measurements)
    metrics, _ = _simulate(model, scenario, measurements.reference.seed)
    checks = []
    ok = True
    lat = metrics["latency_ms"]
    assert isinstance(lat, dict)
    err = metrics["error_rate"]
    tps = metrics["throughput_rps"]
    table = [
        ("p50", lat["p50"], observed.get("p50"), AGREE_P50, True),
        ("error_rate", err, observed.get("error_rate"), AGREE_ERROR_PP, False),
        ("throughput_rps", tps, observed.get("throughput_rps"), AGREE_TPS, True),
    ]
    for name, sim, obs, tol, relative in table:
        assert isinstance(sim, (int, float))
        if obs is None:
            continue
        gap = abs(sim - obs) / abs(obs) if relative and obs != 0 else abs(sim - obs)
        passed = gap <= tol
        ok = ok and passed
        checks.append(
            {
                "metric": name,
                "simulated": sim,
                "observed": obs,
                "gap": round(gap, 4),
                "pass": passed,
            }
        )
    return (checks, ok)


def calibrate(model: SystemModel, measurements: Measurements) -> tuple[SystemModel, dict[str, Any]]:
    """Full v2 pass: latency, capacity, queues with convergence; agreement gate."""
    known = _check_targets(model, measurements)
    warned: list[str] = []
    latency = _latency_factors(known, measurements, warned)
    current = _rebuild(model, latency, {}, {})
    capacity: dict[str, float] = {}
    queues: dict[str, float] = {}
    iterations = 0
    converged = True
    for _ in range(MAX_PASSES):
        iterations += 1
        known_now = {c.id: c for c in current.components}
        new_capacity = _capacity_factors(known_now, measurements, warned)
        new_queues = _queue_factors(current, measurements, warned)
        change = _max_change(new_capacity, new_queues, capacity, queues)
        capacity, queues = new_capacity, new_queues
        current = _rebuild(current, {}, capacity, queues)
        if change < CONVERGE_TOL:
            break
    else:
        converged = False
    factors = _total_factors(model, current, measurements)
    fit_error = max([abs(f - 1.0) for f in factors.values()] or [0.0])
    checks, agreed = _agreement(current, measurements)
    confident = fit_error <= FIT_LIMIT and agreed and converged
    record = {
        "method": "v2-full",
        "source": measurements.source,
        "measured_at": measurements.measured_at,
        "factors": {k: round(v, 4) for k, v in sorted(factors.items())},
        "fit_error": round(fit_error, 4),
        "fit_limit": FIT_LIMIT,
        "iterations": iterations,
        "converged": converged,
        "agreement": checks,
        "model_confidence": "medium" if confident else "low",
        "warnings": sorted(set(warned)),
    }
    data = current.model_dump(mode="json", by_alias=True)
    data["metadata"] = {**(data.get("metadata") or {}), "calibration": record}
    return (SystemModel.model_validate(data), record)


def _total_factors(
    original: SystemModel, final: SystemModel, measurements: Measurements
) -> dict[str, float]:
    """Total per-parameter change vs the input model (what the record reports)."""
    before = {c.id: c for c in original.components}
    factors = {}
    for comp in final.components:
        if comp.id not in measurements.components:
            continue
        prev = before[comp.id]
        if _has(measurements, comp.id, "p50"):
            factors[f"latency.{comp.id}"] = comp.latency_ms.base / prev.latency_ms.base
        if _has(measurements, comp.id, "sat_tps"):
            factors[f"capacity.{comp.id}"] = comp.capacity / prev.capacity
        if _has(measurements, comp.id, "queue_max"):
            factors[f"queue.{comp.id}"] = comp.queue_size / prev.queue_size
    return factors


def _has(measurements: Measurements, cid: str, key: str) -> bool:
    return getattr(measurements.components[cid], key) is not None


def _max_change(
    new_cap: dict[str, float],
    new_q: dict[str, float],
    old_cap: dict[str, float],
    old_q: dict[str, float],
) -> float:
    changes = []
    for cid, factor in new_cap.items():
        prev = old_cap.get(cid, 1.0)
        changes.append(abs(factor - prev) / max(prev, 1e-9))
    for cid, factor in new_q.items():
        prev = old_q.get(cid, 1.0)
        changes.append(abs(factor - prev) / max(prev, 1e-9))
    return max(changes or [0.0])


def calibrate_file(model_path: Path, measurements_path: Path) -> tuple[SystemModel, dict[str, Any]]:
    """Load, validate refs, and calibrate. Model validation errors surface as-is."""
    from shadowbox.dsl import load_model

    model = load_model(model_path)
    return calibrate(model, _read_measurements(measurements_path))
