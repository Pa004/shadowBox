"""D1-backed store for the Cloudflare Worker (M4b-full).

Same signatures as the SQLite store, but async: the D1 binding only speaks
over the Workers runtime. Verified against a fake binding in unit tests;
production verification needs account access (wrangler deploy).
"""

import json
import uuid
from typing import Any, Protocol


class D1Binding(Protocol):
    """Subset of the cloudflare D1 binding used here (prepare/bind/all/run)."""

    def prepare(self, sql: str) -> Any: ...


class AsyncStore(Protocol):
    async def save_model(self, body: dict[str, Any]) -> str: ...
    async def get_model(self, model_id: str) -> dict[str, Any] | None: ...
    async def save_simulation(
        self, model_id: str, scenario: dict[str, Any], seed: int, report: dict[str, Any]
    ) -> str: ...
    async def get_simulation(self, sim_id: str) -> dict[str, Any] | None: ...


class D1Store:
    """Async store over a D1 database binding (Cloudflare Workers)."""

    def __init__(self, db: D1Binding) -> None:
        self._db = db

    async def _all(self, sql: str, *params: Any) -> list[Any]:
        # Rows support string-key access both as dicts (tests) and as JS
        # proxies (Worker runtime): row["col"] works in both worlds.
        stmt = self._db.prepare(sql)
        bound = stmt.bind(*params) if params else stmt
        outcome = await bound.all()
        return list(outcome["results"])

    async def _run(self, sql: str, *params: Any) -> None:
        stmt = self._db.prepare(sql)
        bound = stmt.bind(*params) if params else stmt
        await bound.run()

    async def save_model(self, body: dict[str, Any]) -> str:
        model_id = uuid.uuid4().hex[:16]
        await self._run("INSERT INTO models (id, body) VALUES (?, ?)", model_id, json.dumps(body))
        return model_id

    async def get_model(self, model_id: str) -> dict[str, Any] | None:
        rows = await self._all("SELECT body FROM models WHERE id = ?", model_id)
        if not rows:
            return None
        parsed: dict[str, Any] = json.loads(rows[0]["body"])
        return parsed

    async def save_simulation(
        self, model_id: str, scenario: dict[str, Any], seed: int, report: dict[str, Any]
    ) -> str:
        sim_id = uuid.uuid4().hex[:16]
        await self._run(
            "INSERT INTO simulations (id, model_id, scenario, seed, status, report)"
            " VALUES (?, ?, ?, ?, 'completed', ?)",
            sim_id,
            model_id,
            json.dumps(scenario),
            seed,
            json.dumps(report),
        )
        return sim_id

    async def get_simulation(self, sim_id: str) -> dict[str, Any] | None:
        rows = await self._all(
            "SELECT model_id, scenario, seed, status, report FROM simulations WHERE id = ?", sim_id
        )
        if not rows:
            return None
        row = rows[0]
        return {
            "id": sim_id,
            "model_id": row["model_id"],
            "scenario": json.loads(row["scenario"]),
            "seed": row["seed"],
            "status": row["status"],
            "report": json.loads(row["report"]),
        }
