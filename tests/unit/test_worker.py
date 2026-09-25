"""M4b worker entry test: clear failure outside the Workers runtime."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def test_worker_requires_workers_runtime() -> None:
    path = ROOT / "apps" / "api" / "worker.py"
    spec = importlib.util.spec_from_file_location("sb_worker", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    with pytest.raises(RuntimeError, match="pywrangler"):
        spec.loader.exec_module(module)
