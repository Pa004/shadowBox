"""M0 contract tests: valid model passes, broken fixtures fail with stable codes."""

from pathlib import Path

import pytest

from shadowbox.dsl import load_model, load_scenario
from shadowbox.errors import CycleError, RefError, SchemaError, UnsafeYamlError

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "src" / "shadowbox" / "data" / "example"
FIXTURES = ROOT / "tests" / "fixtures"


def test_valid_model_and_scenario() -> None:
    model = load_model(EXAMPLE / "model.yaml")
    scenario = load_scenario(EXAMPLE / "scenarios" / "db-failure.yaml", model)
    assert [c.id for c in model.components] == ["api", "cache", "database"]
    assert scenario.name == "database-failure"
    assert scenario.workload.rate_rps == 100


def test_cycle_rejected() -> None:
    with pytest.raises(CycleError) as exc:
        load_model(FIXTURES / "cycle.yaml")
    assert exc.value.code == "E_CYCLE"


def test_unknown_ref_rejected() -> None:
    with pytest.raises(RefError) as exc:
        load_model(FIXTURES / "bad-ref.yaml")
    assert exc.value.code == "E_REF"


def test_unknown_fault_target_rejected(tmp_path: Path) -> None:
    model = load_model(EXAMPLE / "model.yaml")
    bad = tmp_path / "scenario.yaml"
    bad.write_text(
        "name: bad\nduration_s: 10\nworkload:\n  rate_rps: 10\n"
        "faults:\n  - target: ghost\n    type: unavailable\n"
        "    start_s: 0\n    duration_s: 1\n",
        encoding="utf-8",
    )
    with pytest.raises(RefError):
        load_scenario(bad, model)


def test_unsafe_yaml_rejected(tmp_path: Path) -> None:
    evil = tmp_path / "evil.yaml"
    evil.write_text("components: !!python/object:os.system [x]\n", encoding="utf-8")
    with pytest.raises(UnsafeYamlError):
        load_model(evil)


def test_missing_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        load_model(tmp_path / "nope.yaml")
