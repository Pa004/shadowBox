"""M2 import tests: compose converts to a valid model with estimated fields."""

from pathlib import Path

import pytest
import yaml

from shadowbox.dsl import load_model
from shadowbox.errors import SchemaError, UnsafeYamlError
from shadowbox.importers.compose import import_compose

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "src" / "shadowbox" / "data" / "example"


def test_compose_imports_three_components() -> None:
    model, warnings = import_compose(EXAMPLE / "docker-compose.yaml")
    assert sorted(c.id for c in model.components) == ["api", "cache", "database"]
    assert {c.type for c in model.components} == {"service", "cache", "database"}
    edges = {(c.from_, c.to) for c in model.connections}
    assert ("api", "cache") in edges
    assert ("api", "database") in edges
    assert ("cache", "database") in edges
    assert len(warnings) == 3  # one estimation warning per component


def test_imported_model_passes_validation(tmp_path: Path) -> None:
    model, _ = import_compose(EXAMPLE / "docker-compose.yaml")
    out = tmp_path / "model.yaml"
    out.write_text(yaml.safe_dump(model.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    reloaded = load_model(out)
    assert len(reloaded.components) == 3


def test_external_dependency_dropped_with_warning(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text(
        "services:\n  web:\n    image: app:1\n    depends_on:\n      - managed-db\n",
        encoding="utf-8",
    )
    model, warnings = import_compose(compose)
    assert len(model.components) == 1
    assert model.connections == []
    assert any("managed-db" in w for w in warnings)


def test_missing_services_rejected(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("version: '3'\n", encoding="utf-8")
    with pytest.raises(SchemaError):
        import_compose(compose)


def test_unsafe_yaml_rejected(tmp_path: Path) -> None:
    compose = tmp_path / "compose.yaml"
    compose.write_text("services: !!python/object:os.system [x]\n", encoding="utf-8")
    with pytest.raises(UnsafeYamlError):
        import_compose(compose)
