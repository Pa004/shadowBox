"""Property tests over a tiny two-component model (Hypothesis defaults: reliable)."""

from hypothesis import given
from hypothesis import strategies as st

from shadowbox.engine import simulate
from shadowbox.metrics import summarize
from shadowbox.model import (
    Component,
    Connection,
    Fault,
    LatencyMs,
    Scenario,
    SystemModel,
    Workload,
)


def _tiny_model() -> SystemModel:
    return SystemModel(
        components=[
            Component(
                id="api",
                type="service",
                capacity=4,
                latency_ms=LatencyMs(base=10, jitter_ms=3),
                timeout_ms=200,
                queue_size=8,
                queue_policy="drop",
            ),
            Component(
                id="db",
                type="database",
                capacity=2,
                latency_ms=LatencyMs(base=5, jitter_ms=2),
                timeout_ms=100,
                queue_size=8,
                queue_policy="fifo",
            ),
        ],
        connections=[Connection(**{"from": "api", "to": "db"})],
    )


def _scenario(kind: str) -> Scenario:
    faults = []
    if kind == "down":
        faults.append(Fault(target="db", type="unavailable", start_s=0, duration_s=2))
    return Scenario(name=kind, duration_s=2, workload=Workload(rate_rps=5), faults=faults)


@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_conservation(seed: int) -> None:
    result = simulate(_tiny_model(), _scenario("ok"), seed)
    assert result.succeeded + result.failed == result.total == 10
    assert len(result.latencies_ms) == result.succeeded


@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_deterministic_hash(seed: int) -> None:
    model = _tiny_model()
    scenario = _scenario("ok")
    first = simulate(model, scenario, seed)
    second = simulate(model, scenario, seed)
    assert first.latencies_ms == second.latencies_ms
    assert (first.succeeded, first.failed) == (second.succeeded, second.failed)


@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_metric_bounds(seed: int) -> None:
    model = _tiny_model()
    scenario = _scenario("down")
    result = simulate(model, scenario, seed)
    metrics = summarize(model, result, scenario.duration_s)
    assert 0.0 <= metrics["error_rate"] <= 1.0  # type: ignore[operator]
    latency = metrics["latency_ms"]
    assert isinstance(latency, dict)
    assert latency["p50"] <= latency["p99"]
    assert result.cascade_depth >= 0


@given(seed=st.integers(min_value=0, max_value=2**31 - 1))
def test_outage_hurts(seed: int) -> None:
    model = _tiny_model()
    healthy = simulate(model, _scenario("ok"), seed)
    broken = simulate(model, _scenario("down"), seed)
    assert broken.failed > healthy.failed
