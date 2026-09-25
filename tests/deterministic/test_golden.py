"""Deterministic golden test: checkout + db-failure + seed 42 must hash identically."""

from pathlib import Path

from shadowbox.dsl import load_model, load_scenario
from shadowbox.engine import simulate
from shadowbox.metrics import summarize
from shadowbox.report import build_report

ROOT = Path(__file__).resolve().parents[2]
CHECKOUT = ROOT / "examples" / "checkout"

# Pinned on first green M1 run; any engine change must justify a hash update here.
GOLDEN_HASH = "ffbf351c71aa9b403191e73df8fd1bcf46f6f72e6946bf6c2044e52c2bc7a080"
GOLDEN_SUCCEEDED = 5000
GOLDEN_FAILED = 1000


def _run(seed: int = 42) -> dict[str, object]:
    model = load_model(CHECKOUT / "model.yaml")
    scenario = load_scenario(CHECKOUT / "scenarios" / "db-failure.yaml", model)
    result = simulate(model, scenario, seed)
    metrics = summarize(model, result, scenario.duration_s)
    return build_report(
        model.model_dump(mode="json", by_alias=True),
        scenario.model_dump(mode="json"),
        seed,
        metrics,
        result.events_processed,
    )


def test_golden_hash_pinned() -> None:
    report = _run()
    assert report["metrics_hash"] == GOLDEN_HASH
    metrics = report["metrics"]
    assert isinstance(metrics, dict)
    requests = metrics["requests"]
    assert isinstance(requests, dict)
    assert requests["succeeded"] == GOLDEN_SUCCEEDED
    assert requests["failed"] == GOLDEN_FAILED


def test_rerun_identical() -> None:
    first = _run()
    second = _run()
    assert first["metrics_hash"] == second["metrics_hash"]
    assert first["metrics"] == second["metrics"]
