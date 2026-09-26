"""D1Store contract test against a fake binding (no account needed)."""

from typing import Any

from fastapi.testclient import TestClient

from shadowbox.api import create_app
from shadowbox.dstore import D1Store


class _FakeStatement:
    def __init__(self, db: "FakeDB", sql: str) -> None:
        self._db = db
        self._sql = sql
        self._params: tuple[Any, ...] = ()

    def bind(self, *params: Any) -> "_FakeStatement":
        self._params = params
        return self

    async def all(self) -> dict[str, list[Any]]:
        return {"results": self._db.query(self._sql, self._params)}

    async def run(self) -> dict[str, bool]:
        self._db.execute(self._sql, self._params)
        return {"success": True}


class FakeDB:
    """Minimal D1-shaped binding over dicts (prepare/bind/all/run)."""

    def __init__(self) -> None:
        self.models: dict[str, str] = {}
        self.sims: dict[str, tuple[str, str, int, str, str]] = {}

    def prepare(self, sql: str) -> _FakeStatement:
        return _FakeStatement(self, sql)

    def query(self, sql: str, params: tuple[Any, ...]) -> list[Any]:
        if sql.startswith("SELECT body FROM models"):
            body = self.models.get(params[0])
            return [{"body": body}] if body is not None else []
        if sql.startswith("SELECT model_id"):
            row = self.sims.get(params[0])
            if row is None:
                return []
            return [
                {
                    "model_id": row[0],
                    "scenario": row[1],
                    "seed": row[2],
                    "status": row[3],
                    "report": row[4],
                }
            ]
        raise AssertionError(f"unexpected query: {sql}")

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        if sql.startswith("INSERT INTO models"):
            self.models[params[0]] = params[1]
        elif sql.startswith("INSERT INTO simulations"):
            self.sims[params[0]] = (params[1], params[2], params[3], "completed", params[4])
        else:
            raise AssertionError(f"unexpected write: {sql}")


async def _round_trip() -> tuple[str, str]:
    store = D1Store(FakeDB())
    model_id = await store.save_model({"components": []})
    assert await store.get_model(model_id) == {"components": []}
    assert await store.get_model("missing") is None
    sim_id = await store.save_simulation(model_id, {"a": 1}, 7, {"metrics": {}})
    found = await store.get_simulation(sim_id)
    assert found is not None and found["seed"] == 7
    assert await store.get_simulation("missing") is None
    return (model_id, sim_id)


def test_dstore_round_trip() -> None:
    import asyncio

    asyncio.run(_round_trip())


def test_app_flow_on_dstore() -> None:
    client = TestClient(create_app(D1Store(FakeDB())))
    body = {
        "components": [
            {
                "id": "a",
                "type": "service",
                "capacity": 1,
                "latency_ms": {"base": 5},
                "timeout_ms": 100,
                "queue_size": 5,
                "queue_policy": "drop",
            }
        ]
    }
    created = client.post("/api/v1/models", json=body)
    assert created.status_code == 201
    assert client.get(f"/api/v1/models/{created.json()['id']}").status_code == 200
