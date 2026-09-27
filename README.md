# ShadowBox

[![CI](https://github.com/Pa004/shadowBox/actions/workflows/ci.yml/badge.svg)](https://github.com/Pa004/shadowBox/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/shadowbox)](https://pypi.org/project/shadowbox/)
[![Python](https://img.shields.io/badge/python-3.13-blue)](https://www.python.org/downloads/release/python-3130/)

Executable architectural model for safe what-if experimentation. Model the system. Experiment safely.

> Scope: headless CLI (validate, simulate, compare, report, import, init, serve) plus local API, static demo, and React Studio. Simulation output is always labeled with assumptions, confidence, and seed — never presented as production measurement.

## Requirements

- Python `>=3.13` (pinned via `.python-version`)
- `uv` for env and runs (no Docker needed)

## Install

With a clone (development):

```powershell
uv python pin 3.13
uv venv
uv sync --group dev
```

Without a clone (use only):

```powershell
uvx --from "shadowbox @ git+https://github.com/Pa004/shadowBox.git@v0.2.0" shadowbox init --out demo
```

## Run in development

```powershell
uv run shadowbox init --out demo
uv run shadowbox import --from demo/docker-compose.yaml --out demo/model2.yaml
uv run shadowbox validate demo/model.yaml --scenario demo/scenarios/db-failure.yaml
uv run shadowbox simulate demo/model.yaml --scenario demo/scenarios/db-failure.yaml --seed 42 --out report.json
uv run shadowbox report report.json --format text
uv run shadowbox compare --a base.json --b report.json
```

Exit codes: `0` valid/pass, `2` scenario regression (compare), `3` invalid input or existing files without `--force` (prints `E_*` code).

Import notes: every performance field is an estimated default (see warnings). Calibrate before trusting output. Sources: `docker-compose.yaml` (services, `depends_on`/`links`) and Kubernetes manifests (workloads; edges only from `shadowbox.io/depends-on: "a, b"` annotation).

Chaos cards ship in the package (`init` writes them to `cards/`): `db-down`, `cache-poison`, `latency-500ms`, `traffic-10x`, `zone-loss`, `slow-dependency`, `queue-overflow`.

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
!wrangler d1 execute shadowbox --remote --file schema.sql  # --remote matters: without it you seed local only
!uv tool install workers-py
!pywrangler sync
!powershell -ExecutionPolicy ByPass -File scripts/vendor-worker.ps1  # bundle local src, not just PyPI deps
!pywrangler deploy
```

Production note: the Worker (`apps/api/worker.py`) serves the same FastAPI app built by `create_app()` with no store, so each request gets a `D1Store` from the `DB` binding (schema in `schema.sql`). Local runs inject SQLite. `D1Store` is contract-tested against a fake binding; production verification needs a real account (M4b-full).

Live demo: `https://shadowbox-api.pablodo004.workers.dev` (static demo at `/`, API under `/api/v1/`). The static demo deploys to Pages as-is and talks to any API base URL.

Open `apps/web/index.html` after `Run` to scrub virtual time: the SVG graph colors failed components red and shows active faults per second (first 500 sampled requests).

## Studio (React + Cytoscape)

Full UI in `apps/studio/` (Vite, strict TS). Needs Node deps (run yourself):

```powershell
cd apps/studio
npm install
npm run build   # tsc plus vite
npm run dev     # /api proxies to 127.0.0.1:8000
```

Run any scenario vs baseline, inspect p99/error verdict, scrub the failure cascade on the Cytoscape graph.

## Environment variables

None required. Server mode reads no env vars yet; Cloudflare D1 bindings arrive with the production Worker swap.

## Project structure

```text
src/shadowbox/         # model, dsl, cli, errors, engine, metrics, report, cards, api, store
src/shadowbox/data/    # canonical example + chaos cards (shipped in the wheel)
schemas/               # model-v1.json, scenario-v1.json
tests/                 # unit, deterministic (golden seed 42), property, integration
tests/fixtures/        # broken models (E_CYCLE, E_REF)
apps/web/              # static demo with replay (no build)
apps/studio/           # React + Cytoscape UI (Vite, strict TS)
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

Local-first: CLI and `serve` need nothing but Python. Demo deploy: Cloudflare Pages (web) + Python Worker (FastAPI via `workers.asgi`) + D1 — see `Deploy (Cloudflare...)` above. No paid service, no credit card at any tier. See `ShadowBox.md` (local spec, git-ignored) for the full contract.
