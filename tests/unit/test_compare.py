"""M3 comparison tests: deltas, thresholds, verdicts, and CLI exit codes."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from shadowbox.cli import app
from shadowbox.compare import compare_reports, parse_thresholds
from shadowbox.errors import SchemaError

runner = CliRunner()


def _report(
    p99: float, error_rate: float, throughput: float, seed: int = 42
) -> dict[str, object]:
    return {
        "seed": seed,
        "metrics": {
            "throughput_rps": throughput,
            "error_rate": error_rate,
            "latency_ms": {"p50": p99 / 2, "p90": p99 - 1, "p95": p99 - 0.5, "p99": p99},
        },
    }


def test_parse_thresholds_ok() -> None:
    parsed = parse_thresholds("p99:+10%,error_rate:+1pp,throughput:-10%")
    assert [(t.metric, t.limit, t.percent) for t in parsed] == [
        ("p99", 10.0, True),
        ("error_rate", 1.0, False),
        ("throughput", 10.0, True),
    ]


def test_parse_thresholds_rejects_units() -> None:
    with pytest.raises(SchemaError):
        parse_thresholds("error_rate:+1%")
    with pytest.raises(SchemaError):
        parse_thresholds("p99:+10pp")
    with pytest.raises(SchemaError):
        parse_thresholds("bogus:+1%")


def test_regression_verdict() -> None:
    result = compare_reports(
        _report(30.0, 0.0, 100.0),
        _report(40.0, 0.0, 100.0),
        parse_thresholds("p99:+10%"),
    )
    assert result.verdict == "regression"
    assert result.breaches == ["p99"]
    assert result.deltas["p99"] == pytest.approx(33.33, abs=0.01)


def test_pass_and_improvement() -> None:
    same = compare_reports(
        _report(30.0, 0.0, 100.0), _report(30.0, 0.0, 100.0), parse_thresholds("p99:+10%")
    )
    assert same.verdict == "pass"
    better = compare_reports(
        _report(30.0, 0.0, 100.0), _report(27.0, 0.0, 100.0), parse_thresholds("p99:+10%")
    )
    assert better.verdict == "improvement"


def test_throughput_drop_is_regression() -> None:
    result = compare_reports(
        _report(30.0, 0.0, 100.0),
        _report(30.0, 0.0, 80.0),
        parse_thresholds("throughput:-10%"),
    )
    assert result.verdict == "regression"


def _write(tmp_path: Path, name: str, payload: dict[str, object]) -> Path:
    path = tmp_path / name
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_cli_compare_exit_codes(tmp_path: Path) -> None:
    base = _write(tmp_path, "a.json", _report(30.0, 0.0, 100.0))
    same = _write(tmp_path, "b.json", _report(30.0, 0.0, 100.0))
    worse = _write(tmp_path, "c.json", _report(40.0, 0.0, 100.0))
    assert runner.invoke(app, ["compare", "--a", str(base), "--b", str(same)]).exit_code == 0
    failed = runner.invoke(app, ["compare", "--a", str(base), "--b", str(worse)])
    assert failed.exit_code == 2
    assert "regression" in failed.output


def test_cli_compare_seed_mismatch_warns(tmp_path: Path) -> None:
    base = _write(tmp_path, "a.json", _report(30.0, 0.0, 100.0, seed=1))
    other = _write(tmp_path, "b.json", _report(30.0, 0.0, 100.0, seed=2))
    done = runner.invoke(app, ["compare", "--a", str(base), "--b", str(other)])
    assert done.exit_code == 0
    assert "E_SEED_MISMATCH" in done.output


def test_cli_compare_invalid_report(tmp_path: Path) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{}", encoding="utf-8")
    done = runner.invoke(app, ["compare", "--a", str(bad), "--b", str(bad)])
    assert done.exit_code == 3


def test_cli_report_renders(tmp_path: Path) -> None:
    payload: dict[str, object] = {
        "engine": "t",
        "seed": 1,
        "metrics": {
            "throughput_rps": 10.0,
            "error_rate": 0.0,
            "latency_ms": {"p50": 1, "p95": 2, "p99": 3},
            "timeouts": 0,
            "cascade_depth": 0,
        },
        "metrics_hash": "abc",
        "confidence": "low",
        "calibration_source": "none",
    }
    path = _write(tmp_path, "r.json", payload)
    assert runner.invoke(app, ["report", str(path), "--format", "text"]).exit_code == 0
    assert runner.invoke(app, ["report", str(path)]).exit_code == 0


def test_cli_serve_help() -> None:
    done = runner.invoke(app, ["serve", "--help"])
    assert done.exit_code == 0
    assert "--port" in done.output
