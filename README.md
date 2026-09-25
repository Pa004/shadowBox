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
uv run shadowbox validate examples/checkout/model.yaml --scenario examples/checkout/scenarios/db-failure.yaml
```

Exit codes: `0` valid, `3` invalid model/scenario (prints `E_*` code).

## Environment variables

None required for M0. Server mode (M4) will document `D1_*` bindings in this section.

## Project structure

```text
src/shadowbox/   # model, dsl, cli, errors (M0)
schemas/         # model-v1.json, scenario-v1.json
examples/        # checkout fixture (api+cache+db) + broken fixtures
tests/           # unit (M0), property/deterministic (M1)
```

## Run tests

```powershell
uv run ruff check .
uv run mypy src
uv run pytest
```

## Deploy notes

M0 has no deploy. Demo deploy (M4): Cloudflare Pages (web) + Python Worker (FastAPI via `workers.asgi`) + D1. No paid service, no credit card at any tier. See `ShadowBox.md` (local spec, git-ignored) for the full contract.
