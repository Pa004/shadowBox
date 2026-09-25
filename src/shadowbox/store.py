"""SQLite persistence for models, simulations, and reports (M4a local server).

Cloud deploy (M4b) swaps this module for a D1-backed store with the same
function signatures; the API layer does not change.
"""

import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS models (
  id TEXT PRIMARY KEY,
  body TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS simulations (
  id TEXT PRIMARY KEY,
  model_id TEXT NOT NULL REFERENCES models(id),
  scenario TEXT NOT NULL,
  seed INTEGER NOT NULL,
  status TEXT NOT NULL,
  report TEXT NOT NULL
);
"""


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


class Store:
    """File-backed store; one connection per call keeps the API thread-safe."""

    def __init__(self, path: Path) -> None:
        self._path = path  # file created lazily on first use, never on import

    def _new_id(self) -> str:
        return uuid.uuid4().hex[:16]

    def save_model(self, body: dict[str, Any]) -> str:
        model_id = self._new_id()
        with _connect(self._path) as conn:
            conn.execute(
                "INSERT INTO models (id, body) VALUES (?, ?)", (model_id, json.dumps(body))
            )
        return model_id

    def get_model(self, model_id: str) -> dict[str, Any] | None:
        with _connect(self._path) as conn:
            row = conn.execute("SELECT body FROM models WHERE id = ?", (model_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def save_simulation(
        self, model_id: str, scenario: dict[str, Any], seed: int, report: dict[str, Any]
    ) -> str:
        sim_id = self._new_id()
        with _connect(self._path) as conn:
            conn.execute(
                "INSERT INTO simulations (id, model_id, scenario, seed, status, report)"
                " VALUES (?, ?, ?, ?, 'completed', ?)",
                (sim_id, model_id, json.dumps(scenario), seed, json.dumps(report)),
            )
        return sim_id

    def get_simulation(self, sim_id: str) -> dict[str, Any] | None:
        with _connect(self._path) as conn:
            row = conn.execute(
                "SELECT model_id, scenario, seed, status, report FROM simulations WHERE id = ?",
                (sim_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "id": sim_id,
            "model_id": row[0],
            "scenario": json.loads(row[1]),
            "seed": row[2],
            "status": row[3],
            "report": json.loads(row[4]),
        }
