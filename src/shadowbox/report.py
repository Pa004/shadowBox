"""Report envelope: metrics plus honesty metadata and a reproducibility hash."""

import hashlib
import json
from typing import Any

ENGINE_VERSION = "shadowbox-m1/0.1.0"

ENGINE_CONFIDENCE = "high"
ENGINE_EVIDENCE = [
    "seeded RNG with golden-hash regression (same inputs, identical hash)",
    "property-based invariants (conservation, determinism, bounds)",
    "unit plus integration suite over model, DSL, engine, and API",
]

FIT_LIMIT = 0.15

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


def _model_confidence(model: dict[str, Any]) -> tuple[str, str, dict[str, Any] | None]:
    """Model fidelity from calibration metadata; engine confidence is separate."""
    metadata = model.get("metadata")
    calibration = metadata.get("calibration") if isinstance(metadata, dict) else None
    if not isinstance(calibration, dict):
        return ("low", "none", None)
    fit_error = calibration.get("fit_error", 1.0)
    assert isinstance(fit_error, (int, float))
    if fit_error <= FIT_LIMIT:
        return ("medium", str(calibration.get("source", "manual")), calibration)
    return ("low", str(calibration.get("source", "manual")), calibration)


def build_report(
    model: dict[str, Any],
    scenario: dict[str, Any],
    seed: int,
    metrics: dict[str, Any],
    events_processed: int,
) -> dict[str, Any]:
    """Envelope the metrics; the hash covers model+scenario+seed+metrics only."""
    payload = {"model": model, "scenario": scenario, "seed": seed, "metrics": metrics}
    model_confidence, source, calibration = _model_confidence(model)
    limitations = list(LIMITATIONS)
    if calibration is not None:
        limitations[0] = (
            f"latencies scaled from {source} medians "
            f"(fit error {calibration.get('fit_error')}); still estimates, not predictions"
        )
    return {
        "engine": ENGINE_VERSION,
        "seed": seed,
        "metrics": metrics,
        "metrics_hash": canonical_hash(payload),
        "assumptions": ASSUMPTIONS,
        "limitations": limitations,
        "confidence": model_confidence,
        "engine_confidence": ENGINE_CONFIDENCE,
        "engine_evidence": ENGINE_EVIDENCE,
        "calibration_source": source,
        "calibration": calibration,
        "events_processed": events_processed,
    }
