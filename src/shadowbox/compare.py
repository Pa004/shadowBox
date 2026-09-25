"""Scenario comparison: numeric deltas plus a threshold verdict (M3)."""

import re
from dataclasses import dataclass

from shadowbox.errors import SchemaError

_THRESHOLD_RE = re.compile(r"^(p50|p90|p95|p99|error_rate|throughput):([+-])(\d+(?:\.\d+)?)(%|pp)$")
DEFAULT_THRESHOLDS = "p99:+10%,error_rate:+1pp,throughput:-10%"


@dataclass(frozen=True)
class Threshold:
    metric: str
    limit: float  # positive magnitude; unit implied by metric
    percent: bool


@dataclass
class Comparison:
    deltas: dict[str, float]
    breaches: list[str]
    verdict: str  # pass | regression | improvement


def parse_thresholds(raw: str) -> list[Threshold]:
    """Parse `p99:+10%,error_rate:+1pp,throughput:-10%` (pp only for error_rate)."""
    parsed: list[Threshold] = []
    for chunk in raw.split(","):
        match = _THRESHOLD_RE.match(chunk.strip())
        if match is None:
            raise SchemaError(f"invalid threshold {chunk!r}; expected metric:±value%|pp")
        metric, _, value, unit = match.groups()
        if metric == "error_rate" and unit != "pp":
            raise SchemaError("error_rate threshold must use pp units")
        if metric != "error_rate" and unit != "%":
            raise SchemaError(f"{metric} threshold must use % units")
        parsed.append(Threshold(metric, float(value), unit == "%"))
    if not parsed:
        raise SchemaError("at least one threshold required")
    return parsed


def _latency(report: dict[str, object], key: str) -> float:
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    latency = metrics["latency_ms"]
    assert isinstance(latency, dict)
    value = latency[key]
    assert isinstance(value, (int, float))
    return float(value)


def _metric(report: dict[str, object], metric: str) -> float:
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    if metric == "error_rate":
        value = metrics["error_rate"]
    elif metric == "throughput":
        value = metrics["throughput_rps"]
    else:
        return _latency(report, metric)
    assert isinstance(value, (int, float))
    return float(value)


def _pct_change(base: float, candidate: float) -> float:
    if base == 0:
        return 0.0 if candidate == 0 else float("inf")
    return (candidate - base) / abs(base) * 100.0


def compare_reports(
    base: dict[str, object], candidate: dict[str, object], thresholds: list[Threshold]
) -> Comparison:
    """Diff candidate vs base; latency/error up is bad, throughput down is bad."""
    deltas: dict[str, float] = {}
    for threshold in thresholds:
        a = _metric(base, threshold.metric)
        b = _metric(candidate, threshold.metric)
        deltas[threshold.metric] = (b - a) * 100.0 if not threshold.percent else _pct_change(a, b)
    breaches = [
        t.metric
        for t in thresholds
        if (deltas[t.metric] > t.limit if t.metric != "throughput" else deltas[t.metric] < -t.limit)
    ]
    if breaches:
        verdict = "regression"
    elif any(
        (deltas[t.metric] < 0 if t.metric != "throughput" else deltas[t.metric] > 0)
        for t in thresholds
    ):
        verdict = "improvement"
    else:
        verdict = "pass"
    return Comparison(deltas, breaches, verdict)


def seed_warning(base: dict[str, object], candidate: dict[str, object]) -> str | None:
    """Warn when reports are not comparable (different seeds); confidence drops."""
    if base.get("seed") != candidate.get("seed"):
        return "seeds differ; treat verdict with low confidence (E_SEED_MISMATCH)"
    return None
