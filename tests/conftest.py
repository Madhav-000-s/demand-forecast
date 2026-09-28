"""Shared fixtures: a small synthetic dataset and a model trained on it.

Tests never read the real Kaggle file, so they run in CI without it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ml.train import Splits, run

SYNTH_STORES = (1, 2)
SYNTH_ITEMS = (1, 2, 3)


def make_sales_frame(first: str = "2015-01-01", last: str = "2017-12-31", seed: int = 7) -> pd.DataFrame:
    """Daily sales with trend, weekly and yearly seasonality and Poisson noise."""
    rng = np.random.default_rng(seed)
    dates = pd.date_range(first, last, freq="D")
    t = np.arange(len(dates))
    weekly = 1 + 0.25 * np.sin(2 * np.pi * dates.dayofweek.to_numpy() / 7)
    yearly = 1 + 0.3 * np.sin(2 * np.pi * dates.dayofyear.to_numpy() / 365.25)
    rows = []
    for store in SYNTH_STORES:
        for item in SYNTH_ITEMS:
            level = 10 + 3 * store + 2 * item
            mean = level * weekly * yearly * (1 + t / 3000)
            sales = rng.poisson(mean)
            rows.append(pd.DataFrame({"date": dates, "store": store, "item": item, "sales": sales}))
    return pd.concat(rows, ignore_index=True)


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
        params={"num_leaves": 15, "min_data_in_leaf": 20, "learning_rate": 0.1},
        max_rounds=150,
    )
    return out
