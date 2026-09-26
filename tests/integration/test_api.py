"""M4a API tests: model -> scenario -> engine -> metrics over HTTP (tmp DB)."""

from pathlib import Path

import yaml
from fastapi.testclient import TestClient

from shadowbox.api import create_app
from shadowbox.store import AsyncSqliteStore

ROOT = Path(__file__).resolve().parents[2]
EXAMPLE = ROOT / "src" / "shadowbox" / "data" / "example"


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(AsyncSqliteStore(tmp_path / "test.db")))


def _model_body() -> dict[str, object]:
    data = yaml.safe_load((EXAMPLE / "model.yaml").read_text())
    assert isinstance(data, dict)
    return data


def _scenario_body() -> dict[str, object]:
    path = EXAMPLE / "scenarios" / "db-failure.yaml"
    data = yaml.safe_load(path.read_text())
    assert isinstance(data, dict)
    return data


def test_full_flow(tmp_path: Path) -> None:
    client = _client(tmp_path)
    created = client.post("/api/v1/models", json=_model_body())
    assert created.status_code == 201
    model_id = created.json()["id"]

    fetched = client.get(f"/api/v1/models/{model_id}")
    assert fetched.status_code == 200

    sim = client.post(
        "/api/v1/simulations",
        params={"model_id": model_id},
        json={"scenario": _scenario_body(), "seed": 42},
    )
    assert sim.status_code == 201, sim.text
    sim_id = sim.json()["id"]
    assert sim.json()["status"] == "completed"
    assert len(sim.json()["metrics_hash"]) == 64

    detail = client.get(f"/api/v1/simulations/{sim_id}")
    assert detail.status_code == 200
    expected = {"total": 6000, "succeeded": 5000, "failed": 1000}
    assert detail.json()["metrics"]["requests"] == expected

    events = client.get(f"/api/v1/simulations/{sim_id}/events", params={"limit": 10})
    assert events.status_code == 200
    assert len(events.json()["events"]) == 10
    assert events.json()["next_cursor"] == 10

    metrics = client.get(f"/api/v1/simulations/{sim_id}/metrics")
    assert metrics.status_code == 200
    assert metrics.json()["error_rate"] == 1000 / 6000

    report = client.get(f"/api/v1/simulations/{sim_id}/report")
    assert report.status_code == 200
    assert report.json()["confidence"] == "low"


def test_invalid_model_rejected(tmp_path: Path) -> None:
    client = _client(tmp_path)
    done = client.post("/api/v1/models", json={"components": []})
    assert done.status_code == 422
    assert done.json()["code"] == "E_SCHEMA"


def test_unknown_ids_404(tmp_path: Path) -> None:
    client = _client(tmp_path)
    assert client.get("/api/v1/models/nope").status_code == 404
    assert client.get("/api/v1/simulations/nope").status_code == 404
    assert client.get("/api/v1/simulations/nope/events").status_code == 404
    assert client.get("/no-such-page").status_code == 404  # no ASSETS binding locally


def test_event_limit_guarded(tmp_path: Path) -> None:
    client = _client(tmp_path)
    model_id = client.post("/api/v1/models", json=_model_body()).json()["id"]
    sim_id = client.post(
        "/api/v1/simulations",
        params={"model_id": model_id},
        json={"scenario": _scenario_body(), "seed": 42},
    ).json()["id"]
    over = client.get(f"/api/v1/simulations/{sim_id}/events", params={"limit": 5000})
    assert over.status_code == 422
