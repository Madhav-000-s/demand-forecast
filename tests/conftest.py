"""Shared fixtures: a small synthetic dataset and a model trained on it.

Tests never read the real Kaggle file, so they run in CI without it.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ml.synthetic import SYNTH_PARAMS, make_sales_frame
from ml.train import Splits, run

# The API tests share one client and send hundreds of requests in milliseconds;
# rate limiting has its own tests (tests/api/test_ratelimit.py).
os.environ.setdefault("RATE_LIMIT_RPS", "0")


@pytest.fixture(scope="session")
def synthetic_csv(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("data") / "train.csv"
    make_sales_frame().to_csv(path, index=False)
    return path


@pytest.fixture(scope="session")
def artifacts(synthetic_csv: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("artifacts")
    run(
        synthetic_csv,
        out,
        model_version="test-1",
        splits=Splits(),
        params=SYNTH_PARAMS,
        max_rounds=150,
    )
    return out
