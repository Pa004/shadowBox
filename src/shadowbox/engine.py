"""Deterministic discrete-event engine (M1).

Virtual time, 1ms resolution, single isolated RNG. No wall-clock reads.
Only event *counts* are kept; full event logs are deferred to M5.
"""

from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field

from shadowbox.errors import TooLargeError
from shadowbox.model import Component, Fault, Scenario, SystemModel

MS_PER_S = 1000
MAX_REQUESTS = 200_000
MAX_SAMPLE = 500  # stored request summaries; full event log deferred to M5


@dataclass
class ComponentStats:
    busy_time_ms: int = 0
    max_queue_depth: int = 0
    timeouts: int = 0


@dataclass
class _Runtime:
    busy_until: list[int] = field(default_factory=list)  # min-heap of slot releases
    waiter_starts: list[int] = field(default_factory=list)  # min-heap of queued starts
    stats: ComponentStats = field(default_factory=ComponentStats)


@dataclass
class RequestSample:
    correlation_id: str
    ok: bool
    latency_ms: int
    failed_at: str | None
    timed_out: bool
    arrival_ms: int
    finish_ms: int


@dataclass
class SimulationResult:
    total: int
    succeeded: int
    failed: int
    timeouts: int
    latencies_ms: list[int]  # end-to-end, successes only
    cascade_depth: int  # max failing-hop index over failed requests
    events_processed: int
    component_stats: dict[str, ComponentStats]
    sample: list[RequestSample] = field(default_factory=list)  # first MAX_SAMPLE


def build_path(model: SystemModel) -> list[Component]:
    """Depth-first traversal from entry points, each component visited once."""
    by_id = {c.id: c for c in model.components}
    incoming = {c.id: 0 for c in model.components}
    adjacency: dict[str, list[str]] = {c.id: [] for c in model.components}
    for conn in model.connections:
        adjacency[conn.from_].append(conn.to)
        incoming[conn.to] += 1
    for neighbours in adjacency.values():
        neighbours.sort()
    path: list[Component] = []
    seen: set[str] = set()

    def visit(node: str) -> None:
        if node in seen:
            return
        seen.add(node)
        path.append(by_id[node])
        for nxt in adjacency[node]:
            visit(nxt)

    for entry in sorted(n for n, deg in incoming.items() if deg == 0):
        visit(entry)
    return path


def _window_ms(fault: Fault) -> tuple[int, int]:
    start = fault.start_s * MS_PER_S
    return (start, start + fault.duration_s * MS_PER_S)


def _effective_capacity(comp: Component, faults: list[Fault]) -> int:
    capacity = comp.capacity
    for fault in faults:
        if fault.type == "resource-saturation":
            return 1
        if fault.type == "capacity-reduction":
            capacity = min(capacity, max(1, int(comp.capacity * fault.factor)))
    return capacity


def _process(
    comp: Component,
    arrival_ms: int,
    runtime: _Runtime,
    faults: list[Fault],
    rng: random.Random,
) -> tuple[bool, int, bool, int]:
    """Run one component visit. Returns (ok, end_ms, timed_out, events)."""
    events = 4  # sent, received, processing-started, processing-completed
    for fault in faults:
        events += 1  # failure-injected observed
        if fault.type == "unavailable":
            return (False, arrival_ms, False, events)
        if fault.type in ("error-rate", "packet-loss") and rng.random() < fault.probability:
            return (False, arrival_ms, False, events)
    extra_ms = sum(f.extra_ms for f in faults if f.type == "latency")
    jitter = rng.randint(0, comp.latency_ms.jitter_ms) if comp.latency_ms.jitter_ms else 0
    service_ms = comp.latency_ms.base + jitter + extra_ms
    capacity = _effective_capacity(comp, faults)
    while runtime.busy_until and runtime.busy_until[0] <= arrival_ms:
        heapq.heappop(runtime.busy_until)
    if len(runtime.busy_until) < capacity:
        start_ms = arrival_ms
    else:
        while runtime.waiter_starts and runtime.waiter_starts[0] <= arrival_ms:
            heapq.heappop(runtime.waiter_starts)
        if len(runtime.waiter_starts) >= comp.queue_size:
            return (False, arrival_ms, False, events)  # queue-full drop
        start_ms = heapq.heappop(runtime.busy_until)  # consume the earliest slot
        heapq.heappush(runtime.waiter_starts, start_ms)
        depth_now = len(runtime.waiter_starts)
        runtime.stats.max_queue_depth = max(runtime.stats.max_queue_depth, depth_now)
    wait_ms = start_ms - arrival_ms
    if wait_ms >= comp.timeout_ms:
        runtime.stats.timeouts += 1
        return (False, arrival_ms + comp.timeout_ms, True, events)  # gave up waiting
    if service_ms > comp.timeout_ms - wait_ms:
        busy_until = start_ms + (comp.timeout_ms - wait_ms)
        runtime.stats.busy_time_ms += busy_until - start_ms
        runtime.stats.timeouts += 1
        heapq.heappush(runtime.busy_until, busy_until)
        return (False, busy_until, True, events)
    busy_until = start_ms + service_ms
    runtime.stats.busy_time_ms += service_ms
    heapq.heappush(runtime.busy_until, busy_until)
    return (True, busy_until, False, events)


@dataclass
class _RequestOutcome:
    ok: bool
    latency_ms: int
    failed_at: str | None
    timed_out: bool
    finish_ms: int


def simulate(model: SystemModel, scenario: Scenario, seed: int) -> SimulationResult:
    """Run the scenario deterministically; same inputs always give same outputs."""
    total = scenario.workload.rate_rps * scenario.duration_s
    if total > MAX_REQUESTS:
        raise TooLargeError(f"{total} requests exceed cap of {MAX_REQUESTS}")
    path = build_path(model)
    windows: dict[str, list[tuple[int, int, Fault]]] = {}
    for fault in scenario.faults:
        start, end = _window_ms(fault)
        windows.setdefault(fault.target, []).append((start, end, fault))
    runtimes = {c.id: _Runtime() for c in model.components}
    rng = random.Random(seed)
    interval_ms = MS_PER_S / scenario.workload.rate_rps
    # Stratified sample across the whole run (every stride-th request), so the
    # replay sees faults anywhere in the window instead of only the start.
    stride = max(1, (total + MAX_SAMPLE - 1) // MAX_SAMPLE)
    latencies: list[int] = []
    sample: list[RequestSample] = []
    succeeded = 0
    failed = 0
    timeouts = 0
    cascade_depth = 0
    events = 0
    for i in range(total):
        arrival_ms = int(i * interval_ms)
        cursor_ms = arrival_ms
        events += 2  # request-created, request-completed
        outcome = _RequestOutcome(True, 0, None, False, arrival_ms)
        for depth, comp in enumerate(path):
            active = windows.get(comp.id, [])
            faults = [f for (start, end, f) in active if start <= cursor_ms < end]
            ok, end_ms, timed_out, delta = _process(comp, cursor_ms, runtimes[comp.id], faults, rng)
            events += delta
            if not ok:
                failed += 1
                cascade_depth = max(cascade_depth, depth)
                timeouts += 1 if timed_out else 0
                outcome = _RequestOutcome(False, 0, comp.id, timed_out, end_ms)
                break
            cursor_ms = end_ms
        else:
            succeeded += 1
            latencies.append(cursor_ms - arrival_ms)
            outcome = _RequestOutcome(True, cursor_ms - arrival_ms, None, False, cursor_ms)
        if i % stride == 0 and len(sample) < MAX_SAMPLE:
            sample.append(
                RequestSample(
                    correlation_id=f"req-{i:06d}",
                    ok=outcome.ok,
                    latency_ms=outcome.latency_ms,
                    failed_at=outcome.failed_at,
                    timed_out=outcome.timed_out,
                    arrival_ms=arrival_ms,
                    finish_ms=outcome.finish_ms,
                )
            )
    return SimulationResult(
        total=total,
        succeeded=succeeded,
        failed=failed,
        timeouts=timeouts,
        latencies_ms=latencies,
        cascade_depth=cascade_depth,
        events_processed=events,
        component_stats={cid: rt.stats for cid, rt in runtimes.items()},
        sample=sample,
    )
