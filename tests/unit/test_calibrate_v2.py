"""v2 calibration: capacity, queues, convergence, and the agreement gate."""

import tempfile
from pathlib import Path

import yaml

from shadowbox.calibrate import Measurements, _read_measurements, calibrate
from shadowbox.dsl import load_model
from shadowbox.engine import simulate
from shadowbox.metrics import summarize
from shadowbox.model import Scenario, Workload

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "src" / "shadowbox" / "data" / "example"

REF = {"rate_rps": 20, "duration_s": 5, "seed": 3}


def _self_measurements() -> dict:
    """Measurements generated FROM the example model: perfect agreement expected."""
    model = load_model(EXAMPLE / "model.yaml")
    scenario = Scenario(
        name="ref", duration_s=REF["duration_s"], workload=Workload(rate_rps=REF["rate_rps"])
    )
    result = simulate(model, scenario, REF["seed"])
    metrics = summarize(model, result, scenario.duration_s)
    lat = metrics["latency_ms"]
    assert isinstance(lat, dict)
    comps = {}
    for c in model.components:
        service_s = (c.latency_ms.base + c.latency_ms.jitter_ms / 2) / 1000
        depth = metrics["components"][c.id]["queue_depth"]
        assert isinstance(depth, int)
        comps[c.id] = {
            "p50": float(c.latency_ms.base),
            "sat_tps": c.capacity / service_s,
            "queue_max": max(1, depth),
        }
    return Measurements.model_validate(
        {
            "source": "synthetic-self",
            "measured_at": "2026-10-01T00:00:00+00:00",
            "reference": {
                **REF,
                "observed": {
                    "p50": lat["p50"],
                    "error_rate": metrics["error_rate"],
                    "throughput_rps": metrics["throughput_rps"],
                },
            },
            "components": comps,
        }
    ).model_dump()


def _dump(payload: dict) -> Path:
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as fh:
        yaml.safe_dump(payload, fh)
        return Path(fh.name)


def test_self_consistency_is_medium() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    calibrated, record = calibrate(model, _read_measurements(_dump(_self_measurements())))
    assert record["method"] == "v2-full"
    assert record["converged"] is True
    assert record["fit_error"] == 0.0
    assert record["model_confidence"] == "medium"
    assert all(check["pass"] for check in record["agreement"])
    assert calibrated.components[0].latency_ms.base == model.components[0].latency_ms.base


def test_capacity_factor_math() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    payload = {
        "source": "manual",
        "measured_at": "2026-10-01T00:00:00+00:00",
        "components": {"api": {"p50": 20.0, "sat_tps": 1000.0}},
    }
    calibrated, record = calibrate(model, _read_measurements(_dump(payload)))
    api = next(c for c in calibrated.components if c.id == "api")
    # total change 50 -> 22 reported (per-pass factor was 0.45, then converged)
    assert api.capacity == 22, api.capacity
    assert record["factors"]["capacity.api"] == 22 / 50


def test_agreement_failure_stays_low() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    payload = {
        "source": "manual",
        "measured_at": "2026-10-01T00:00:00+00:00",
        "reference": {"rate_rps": 10, "duration_s": 2, "seed": 1, "observed": {"p50": 500.0}},
        "components": {"api": {"p50": 20.0}},
    }
    _, record = calibrate(model, _read_measurements(_dump(payload)))
    assert record["model_confidence"] == "low"
    assert any(not c["pass"] for c in record["agreement"])


def test_queue_search_terminates() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    payload = {
        "source": "manual",
        "measured_at": "2026-10-01T00:00:00+00:00",
        "components": {"api": {"p50": 20.0, "queue_max": 50}},
    }
    calibrated, record = calibrate(model, _read_measurements(_dump(payload)))
    assert record["iterations"] <= 3
    api = next(c for c in calibrated.components if c.id == "api")
    assert 1 <= api.queue_size <= 10000
