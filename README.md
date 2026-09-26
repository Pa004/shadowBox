# ShadowBox

Executable architectural model for safe what-if experimentation. Model the system. Experiment safely.

> M0 scope: contracts + `validate` only (headless). The simulation engine lands in M1. Simulation output is always labeled with assumptions, confidence, and seed — never presented as production measurement.

## Requirements

- Python `>=3.13` (pinned via `.python-version`)
- `uv` for env and runs (no Docker needed for M0)

## Install

```powershell
uv python pin 3.13
uv venv
uv sync --group dev
```

## Run in development

```powershell
uv run shadowbox import --from examples/checkout/docker-compose.yaml --out model.yaml
uv run shadowbox validate examples/checkout/model.yaml --scenario examples/checkout/scenarios/db-failure.yaml
uv run shadowbox simulate examples/checkout/model.yaml --scenario examples/checkout/scenarios/db-failure.yaml --seed 42 --out report.json
uv run shadowbox report report.json --format text
uv run shadowbox compare --a base.json --b report.json
```

Exit codes: `0` valid/pass, `2` scenario regression (compare), `3` invalid model/scenario/report (prints `E_*` code).

Import notes: every performance field is an estimated default (see warnings). Calibrate before trusting output.

Chaos cards in `scenarios/` run against the checkout model: `db-down`, `cache-poison`, `latency-500ms`, `traffic-10x`, `zone-loss`, `slow-dependency`, `queue-overflow`.

## API server (local)

```powershell
uv run uvicorn shadowbox.api:app --port 8000
# or: uv run shadowbox serve --port 8000
```

Endpoints: `POST /api/v1/models`, `GET /api/v1/models/{id}`, `POST /api/v1/simulations?model_id=...`, `GET /api/v1/simulations/{id}[/events|/metrics|/report]`. Events are paginated (`limit` 1..1000, `cursor` offset over the stored 500-request sample). State lives in `shadowbox.db` (git-ignored, created on first use). The API has no authentication: bind to localhost (`serve` defaults to `127.0.0.1`) and never expose it directly to the internet.

## Deploy (Cloudflare free tier, no card)

Scaffold ready in `wrangler.jsonc` + `schema.sql` + `apps/api/worker.py` + `apps/web/` (static demo, no build step). Remaining steps need your Cloudflare account:

```powershell
!npm install -g wrangler
!wrangler login
!wrangler d1 create shadowbox  # paste database_id into wrangler.jsonc
!wrangler d1 execute shadowbox --file schema.sql
!uvx --from workers-py pywrangler dev   # local Worker emulation, no account needed
!wrangler deploy
```

Production note: the Worker serves the same FastAPI app; swapping the SQLite file store for the D1 binding is a follow-up task verified against a real account (M4b-full). The static demo deploys to Pages as-is and talks to any API base URL.

Open `apps/web/index.html` after `Run` to scrub virtual time: the SVG graph colors failed components red and shows active faults per second (first 500 sampled requests).

## Environment variables

None required for M0. Server mode (M4) will document `D1_*` bindings in this section.

## Project structure

```text
src/shadowbox/   # model, dsl, cli, errors, engine, metrics, report
schemas/         # model-v1.json, scenario-v1.json
examples/        # checkout fixture (api+cache+db) + broken fixtures
tests/           # unit, deterministic (golden seed 42), property (Hypothesis)
```

## Run tests

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

Benchmarks (reference: i7-1255U, 16GB, Python 3.13; SLO: 50k events < 2s):

- checkout db-failure (6k reqs, 85k events): ~0.05s
- 60k reqs, 840k events: ~0.6s

## Deploy notes

M0 has no deploy. Demo deploy (M4): Cloudflare Pages (web) + Python Worker (FastAPI via `workers.asgi`) + D1. No paid service, no credit card at any tier. See `ShadowBox.md` (local spec, git-ignored) for the full contract.
