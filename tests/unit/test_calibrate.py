"""Calibration tests: factors, fit rule, guards, and report mapping."""

from pathlib import Path

import pytest
import yaml
from typer.testing import CliRunner

from shadowbox.calibrate import _read_measurements, calibrate, calibrate_file
from shadowbox.cli import app
from shadowbox.dsl import load_model
from shadowbox.engine import simulate
from shadowbox.errors import RefError, SchemaError
from shadowbox.metrics import summarize
from shadowbox.model import Scenario, SystemModel, Workload
from shadowbox.report import build_report

runner = CliRunner()
ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "src" / "shadowbox" / "data" / "example"

MEASURED_CLOSE = {
    "source": "manual",
    "measured_at": "2026-10-01T00:00:00+00:00",
    "components": {"api": {"p50": 22.0}, "cache": {"p50": 2.0}, "database": {"p50": 5.0}},
}

MEASURED_FAR = {
    "source": "manual",
    "measured_at": "2026-10-01T00:00:00+00:00",
    "components": {"api": {"p50": 40.0}, "cache": {"p50": 2.0}, "database": {"p50": 5.0}},
}


def _write_measurements(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "measured.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def _read(tmp_path: Path, payload: dict):
    return _read_measurements(_write_measurements(tmp_path, payload))


def _report_for(model: SystemModel, seed: int = 42) -> dict:
    scenario = Scenario(name="probe", duration_s=5, workload=Workload(rate_rps=10))
    result = simulate(model, scenario, seed)
    metrics = summarize(model, result, scenario.duration_s)
    return build_report(
        model.model_dump(mode="json", by_alias=True),
        scenario.model_dump(mode="json"),
        seed,
        metrics,
        result.events_processed,
    )


def test_close_fit_is_medium(tmp_path: Path) -> None:
    model = load_model(EXAMPLE / "model.yaml")
    calibrated, record = calibrate(model, _read(tmp_path, MEASURED_CLOSE))
    assert record["model_confidence"] == "medium"
    assert record["fit_error"] <= 0.15
    api = next(c for c in calibrated.components if c.id == "api")
    assert api.latency_ms.base == 22
    report = _report_for(calibrated)
    assert report["confidence"] == "medium"
    assert report["engine_confidence"] == "high"
    assert report["calibration_source"] == "manual"
    assert "uncalibrated" not in report["limitations"][0]


def test_far_fit_stays_low(tmp_path: Path) -> None:
    model = load_model(EXAMPLE / "model.yaml")
    _, record = calibrate(model, _read(tmp_path, MEASURED_FAR))
    assert record["model_confidence"] == "low"
    assert record["fit_error"] > 0.15


def test_uncalibrated_stays_low() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    report = _report_for(model)
    assert report["confidence"] == "low"
    assert report["calibration_source"] == "none"
    assert report["calibration"] is None


def test_unknown_target_rejected(tmp_path: Path) -> None:
    model = load_model(EXAMPLE / "model.yaml")
    bad = dict(MEASURED_CLOSE)
    bad["components"] = {"ghost": {"p50": 1.0}}
    with pytest.raises(RefError):
        calibrate(model, _read_measurements(_write_measurements(tmp_path, bad)))


def test_bad_measurements_rejected(tmp_path: Path) -> None:
    path = tmp_path / "measured.yaml"
    path.write_text("components: []\n", encoding="utf-8")
    with pytest.raises(SchemaError):
        calibrate_file(EXAMPLE / "model.yaml", path)


def test_cli_calibrate_flow(tmp_path: Path) -> None:
    out = tmp_path / "calibrated.yaml"
    measured = _write_measurements(tmp_path, MEASURED_CLOSE)
    args = [
        "calibrate",
        str(EXAMPLE / "model.yaml"),
        "--measurements",
        str(measured),
        "--out",
        str(out),
    ]
    done = runner.invoke(app, args)
    assert done.exit_code == 0, done.output
    assert "model_confidence=medium" in done.output
    assert load_model(out).model_dump()["metadata"]["calibration"]["fit_error"] <= 0.15
