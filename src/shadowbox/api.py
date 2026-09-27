"""FastAPI surface over the headless core (local server and Worker share it).

Local-only: no authentication; bind to localhost unless you know why not.
The Worker injects a D1 store per request; local runs use SQLite.
"""

from dataclasses import asdict as _asdict
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError

from shadowbox import engine as engine_mod
from shadowbox.dstore import AsyncStore, D1Store
from shadowbox.errors import ShadowBoxError
from shadowbox.metrics import summarize
from shadowbox.model import Scenario, SystemModel
from shadowbox.report import build_report
from shadowbox.store import AsyncSqliteStore

MAX_EVENT_LIMIT = 1000


class ScenarioIn(BaseModel):
    scenario: dict[str, Any]
    seed: int = 42


def _as_422(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": code, "detail": message})


def create_app(store: AsyncStore | None = None) -> FastAPI:
    """Build the app; without a store, each request uses the D1 binding (Worker)."""
    app = FastAPI(title="ShadowBox", version="0.3.0")
    # Public demo API without credentials: browsers calling from Pages or
    # localhost need permissive CORS; nothing sensitive crosses the wire.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    async def get_store(request: Request) -> AsyncStore:
        if store is not None:
            return store
        # env is a JS proxy on the Worker (not a dict): attribute access only.
        env = request.scope.get("env")
        db = getattr(env, "DB", None) if env is not None else None
        assert db is not None, "D1 binding missing (Worker only)"
        return D1Store(db)

    @app.post("/api/v1/models", status_code=201)
    async def create_model(
        body: dict[str, Any], current: AsyncStore = Depends(get_store)
    ) -> dict[str, str]:
        try:
            SystemModel.model_validate(body)
        except ValidationError as exc:
            return _as_422("E_SCHEMA", str(exc))  # type: ignore[return-value]
        return {"id": await current.save_model(body)}

    @app.get("/api/v1/models/{model_id}")
    async def get_model(model_id: str, current: AsyncStore = Depends(get_store)) -> dict[str, Any]:
        body = await current.get_model(model_id)
        if body is None:
            raise HTTPException(status_code=404, detail="model not found")
        return {"id": model_id, "model": body}

    @app.post("/api/v1/simulations", status_code=201)
    async def create_simulation(
        model_id: str, payload: ScenarioIn, current: AsyncStore = Depends(get_store)
    ) -> dict[str, Any]:
        body = await current.get_model(model_id)
        if body is None:
            raise HTTPException(status_code=404, detail="model not found")
        try:
            system = SystemModel.model_validate(body)
            scenario = Scenario.model_validate(payload.scenario.get("scenario", payload.scenario))
            result = engine_mod.simulate(system, scenario, payload.seed)
            metrics = summarize(system, result, scenario.duration_s)
            report = build_report(
                system.model_dump(mode="json", by_alias=True),
                scenario.model_dump(mode="json"),
                payload.seed,
                metrics,
                result.events_processed,
            )
            report["sample"] = [_asdict(s) for s in result.sample]
        except ShadowBoxError as exc:
            return _as_422(exc.code, str(exc))  # type: ignore[return-value]
        sim_id = await current.save_simulation(model_id, payload.scenario, payload.seed, report)
        return {"id": sim_id, "status": "completed", "metrics_hash": report["metrics_hash"]}

    @app.get("/api/v1/simulations/{sim_id}")
    async def get_simulation(
        sim_id: str, current: AsyncStore = Depends(get_store)
    ) -> dict[str, Any]:
        found = await current.get_simulation(sim_id)
        if found is None:
            raise HTTPException(status_code=404, detail="simulation not found")
        report = found["report"]
        assert isinstance(report, dict)
        return {
            "id": sim_id,
            "status": found["status"],
            "metrics_hash": report.get("metrics_hash"),
            "metrics": report.get("metrics"),
        }

    @app.get("/api/v1/simulations/{sim_id}/events")
    async def get_events(
        sim_id: str, current: AsyncStore = Depends(get_store), limit: int = 100, cursor: int = 0
    ) -> dict[str, Any]:
        found = await current.get_simulation(sim_id)
        if found is None:
            raise HTTPException(status_code=404, detail="simulation not found")
        if limit < 1 or limit > MAX_EVENT_LIMIT:
            raise HTTPException(status_code=422, detail=f"limit must be 1..{MAX_EVENT_LIMIT}")
        if cursor < 0:
            raise HTTPException(status_code=422, detail="cursor must be >= 0")
        report = found["report"]
        assert isinstance(report, dict)
        sample = report.get("sample", [])
        assert isinstance(sample, list)
        page = sample[cursor : cursor + limit]
        nxt = cursor + len(page)
        return {
            "events": page,
            "next_cursor": nxt if nxt < len(sample) else None,
            "total_sampled": len(sample),
        }

    @app.get("/api/v1/simulations/{sim_id}/metrics")
    async def get_metrics(
        sim_id: str, current: AsyncStore = Depends(get_store)
    ) -> dict[str, Any]:
        found = await current.get_simulation(sim_id)
        if found is None:
            raise HTTPException(status_code=404, detail="simulation not found")
        report = found["report"]
        assert isinstance(report, dict)
        metrics = report.get("metrics")
        assert isinstance(metrics, dict)
        return metrics

    @app.get("/api/v1/simulations/{sim_id}/report")
    async def get_report(sim_id: str, current: AsyncStore = Depends(get_store)) -> dict[str, Any]:
        found = await current.get_simulation(sim_id)
        if found is None:
            raise HTTPException(status_code=404, detail="simulation not found")
        report = found["report"]
        assert isinstance(report, dict)
        return report

    @app.get("/{path:path}", include_in_schema=False)
    async def frontend(path: str, request: Request) -> Any:
        """Serve Static Assets on the Worker; plain 404 anywhere else."""
        try:
            env = request.scope.get("env")
            fetcher = getattr(getattr(env, "ASSETS", None), "fetch", None)
            if fetcher is None:
                raise HTTPException(status_code=404, detail="not found")
            target = path if path else "index.html"
            resp = await fetcher(f"https://assets.local/{target}")
            if int(resp.status) == 404:
                raise HTTPException(status_code=404, detail="not found")
            # ASSETS.fetch yields a pyodide FetchResponse: buffer()/bytes()/text().
            body = bytes(await resp.bytes())
            content_type = str(resp.headers.get("content-type") or "application/octet-stream")
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"asset unavailable: {exc}") from exc
        return Response(content=body, status_code=int(resp.status), media_type=content_type)

    return app


app = create_app(AsyncSqliteStore(Path("shadowbox.db")))
