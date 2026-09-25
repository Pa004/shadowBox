"""Report envelope: metrics plus honesty metadata and a reproducibility hash."""

import hashlib
import json
from typing import Any

ENGINE_VERSION = "shadowbox-m1/0.1.0"

ASSUMPTIONS = [
    "sync calls only",
    "depth-first traversal, each component visited once per request",
    "deterministic uniform arrivals",
    "no auto-retry (max_retries unsupported in M1)",
    "no GC pause or infrastructure noise model",
]

LIMITATIONS = [
    "uncalibrated latencies: outputs are what-if illustrations, not predictions",
    "queueing is per-component FIFO with fixed capacity; no backpressure protocol",
]


def canonical_hash(payload: dict[str, Any]) -> str:
    """SHA-256 over canonical JSON (sorted keys, compact separators)."""
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def build_report(
    model: dict[str, Any],
    scenario: dict[str, Any],
    seed: int,
    metrics: dict[str, Any],
    events_processed: int,
) -> dict[str, Any]:
    """Envelope the metrics; the hash covers model+scenario+seed+metrics only."""
    payload = {"model": model, "scenario": scenario, "seed": seed, "metrics": metrics}
    return {
        "engine": ENGINE_VERSION,
        "seed": seed,
        "metrics": metrics,
        "metrics_hash": canonical_hash(payload),
        "assumptions": ASSUMPTIONS,
        "limitations": LIMITATIONS,
        "confidence": "low",
        "calibration_source": "none",
        "events_processed": events_processed,
    }
