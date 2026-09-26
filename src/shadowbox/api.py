"""FastAPI surface over the headless core (M4a local server, M4b Worker later).

Runs synchronously and returns the completed simulation (201) with a
`status` field the Worker async path will reuse for queued/running states.
Local-only: no authentication; bind to localhost unless you know why not.
"""

from dataclasses import asdict as _asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ValidationError

from shadowbox import engine as engine_mod
from shadowbox.errors import ShadowBoxError
from shadowbox.metrics import summarize
from shadowbox.model import Scenario, SystemModel
from shadowbox.report import build_report
from shadowbox.store import Store

MAX_EVENT_LIMIT = 1000

app = FastAPI(title="ShadowBox", version="0.1.0")
store = Store(Path("shadowbox.db"))


class ScenarioIn(BaseModel):
    scenario: dict[str, Any]
    seed: int = 42


def _as_422(code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=422, content={"code": code, "detail": message})


@app.post("/api/v1/models", status_code=201)
def create_model(body: dict[str, Any]) -> dict[str, str]:
    try:
        SystemModel.model_validate(body)
    except ValidationError as exc:
        return _as_422("E_SCHEMA", str(exc))  # type: ignore[return-value]
    return {"id": store.save_model(body)}


@app.get("/api/v1/models/{model_id}")
def get_model(model_id: str) -> dict[str, Any]:
    body = store.get_model(model_id)
    if body is None:
        raise HTTPException(status_code=404, detail="model not found")
    return {"id": model_id, "model": body}


@app.post("/api/v1/simulations", status_code=201)
def create_simulation(model_id: str, payload: ScenarioIn) -> dict[str, Any]:
    body = store.get_model(model_id)
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
        sample = [_asdict(s) for s in result.sample]
        report["sample"] = sample
    except ShadowBoxError as exc:
        return _as_422(exc.code, str(exc))  # type: ignore[return-value]
    sim_id = store.save_simulation(model_id, payload.scenario, payload.seed, report)
    return {"id": sim_id, "status": "completed", "metrics_hash": report["metrics_hash"]}


@app.get("/api/v1/simulations/{sim_id}")
def get_simulation(sim_id: str) -> dict[str, Any]:
    found = store.get_simulation(sim_id)
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
def get_events(sim_id: str, limit: int = 100, cursor: int = 0) -> dict[str, Any]:
    found = store.get_simulation(sim_id)
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
def get_metrics(sim_id: str) -> dict[str, Any]:
    found = store.get_simulation(sim_id)
    if found is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    report = found["report"]
    assert isinstance(report, dict)
    metrics = report.get("metrics")
    assert isinstance(metrics, dict)
    return metrics


@app.get("/api/v1/simulations/{sim_id}/report")
def get_report(sim_id: str) -> dict[str, Any]:
    found = store.get_simulation(sim_id)
    if found is None:
        raise HTTPException(status_code=404, detail="simulation not found")
    report = found["report"]
    assert isinstance(report, dict)
    return report
