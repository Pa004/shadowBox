"""k8s import tests: workloads convert, edges need the explicit annotation."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from shadowbox.cli import app
from shadowbox.dsl import load_model
from shadowbox.errors import SchemaError
from shadowbox.importers.kubernetes import import_kubernetes

runner = CliRunner()

MANIFEST = """\
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api
  annotations:
    shadowbox.io/depends-on: "cache, database"
spec:
  template:
    spec:
      containers:
        - name: api
          image: checkout/api:1.4
---
apiVersion: v1
kind: Service
metadata:
  name: api-svc
spec:
  selector:
    app: api
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cache
spec:
  template:
    spec:
      containers:
        - name: cache
          image: redis:7
---
apiVersion: apps/v1
kind: StatefulSet
metadata:
  name: database
spec:
  template:
    spec:
      containers:
        - name: db
          image: postgres:16
"""


def _write(tmp_path: Path, text: str = MANIFEST) -> Path:
    path = tmp_path / "manifests.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_workloads_import_with_annotation_edges(tmp_path: Path) -> None:
    model, warnings = import_kubernetes(_write(tmp_path))
    assert sorted(c.id for c in model.components) == ["api", "cache", "database"]
    assert {c.type for c in model.components} == {"service", "cache", "database"}
    edges = {(c.from_, c.to) for c in model.connections}
    assert edges == {("api", "cache"), ("api", "database")}
    assert any("non-workload" in w for w in warnings)  # the Service is skipped


def test_unknown_annotation_target_dropped(tmp_path: Path) -> None:
    text = MANIFEST.replace('"cache, database"', '"ghost"')
    model, warnings = import_kubernetes(_write(tmp_path, text))
    assert model.connections == []
    assert any("ghost" in w and "dropped" in w for w in warnings)


def test_imported_model_validates(tmp_path: Path) -> None:
    import yaml

    model, _ = import_kubernetes(_write(tmp_path))
    out = tmp_path / "model.yaml"
    out.write_text(yaml.safe_dump(model.model_dump(mode="json", by_alias=True)), encoding="utf-8")
    assert len(load_model(out).components) == 3


def test_no_workloads_rejected(tmp_path: Path) -> None:
    path = _write(tmp_path, "apiVersion: v1\nkind: ConfigMap\nmetadata:\n  name: cfg\n")
    with pytest.raises(SchemaError):
        import_kubernetes(path)


def test_empty_file_rejected(tmp_path: Path) -> None:
    with pytest.raises(SchemaError):
        import_kubernetes(_write(tmp_path, ""))


def test_cli_auto_detects_multidoc_manifest(tmp_path: Path) -> None:
    manifest = _write(tmp_path)
    out = tmp_path / "model.yaml"
    done = runner.invoke(app, ["import", "--from", str(manifest), "--out", str(out)])
    assert done.exit_code == 0, done.output
    assert len(load_model(out).components) == 3
