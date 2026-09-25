"""Metric aggregation over a finished simulation (exact percentiles)."""

import math

from shadowbox.engine import MS_PER_S, SimulationResult
from shadowbox.model import SystemModel


def percentile(sorted_values: list[int], pct: float) -> float:
    """Nearest-rank percentile; empty input yields 0.0 (no successful requests)."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil((pct / 100.0) * len(sorted_values)))
    return float(sorted_values[rank - 1])


def summarize(
    model: SystemModel,
    result: SimulationResult,
    duration_s: int,
) -> dict[str, object]:
    """Aggregate counts, exact latency percentiles, and per-component stats."""
    ordered = sorted(result.latencies_ms)
    by_id = {c.id: c for c in model.components}
    components = {}
    for cid in sorted(result.component_stats):
        stats = result.component_stats[cid]
        capacity = by_id[cid].capacity
        components[cid] = {
            "utilization": stats.busy_time_ms / (capacity * duration_s * MS_PER_S),
            "queue_depth": stats.max_queue_depth,
            "timeouts": stats.timeouts,
        }
    total = result.total
    return {
        "throughput_rps": result.succeeded / duration_s if duration_s else 0.0,
        "error_rate": result.failed / total if total else 0.0,
        "latency_ms": {
            "p50": percentile(ordered, 50),
            "p90": percentile(ordered, 90),
            "p95": percentile(ordered, 95),
            "p99": percentile(ordered, 99),
        },
        "timeouts": result.timeouts,
        "retries": 0,  # auto-retry disabled in MVP; scenario max_retries lands in M3
        "cascade_depth": result.cascade_depth,
        "requests": {"total": total, "succeeded": result.succeeded, "failed": result.failed},
        "components": components,
    }
