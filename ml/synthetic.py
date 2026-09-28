"""Synthetic store-item sales, used by tests and CI image builds (no Kaggle data needed)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from ml.train import Splits, run

SYNTH_STORES = (1, 2)
SYNTH_ITEMS = (1, 2, 3)
SYNTH_PARAMS = {"num_leaves": 15, "min_data_in_leaf": 20, "learning_rate": 0.1}


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


def make_artifacts(workdir: Path, out: Path, model_version: str = "synthetic") -> dict:
    """Train a small model on synthetic data and write a full artifact set to ``out``."""
    workdir.mkdir(parents=True, exist_ok=True)
    csv = workdir / "synthetic.csv"
    make_sales_frame().to_csv(csv, index=False)
    return run(csv, out, model_version=model_version, splits=Splits(), params=SYNTH_PARAMS, max_rounds=150)


if __name__ == "__main__":
    import argparse
    import tempfile

    p = argparse.ArgumentParser(description="Write synthetic model artifacts (for CI image builds)")
    p.add_argument("--out", type=Path, default=Path("artifacts"))
    p.add_argument("--model-version", default="synthetic-ci")
    a = p.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        meta = make_artifacts(Path(tmp), a.out, a.model_version)
    print(f"wrote synthetic artifacts {meta['model_version']} to {a.out}")
