from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from ml.features import FEATURE_NAMES
from ml.train import HISTORY_DAYS


def test_training_writes_all_artifacts(artifacts: Path) -> None:
    for name in ["model.txt", "metadata.json", "metrics.json", "reference_stats.json", "history.npz"]:
        assert (artifacts / name).is_file(), name


def test_metadata_describes_the_model(artifacts: Path) -> None:
    meta = json.loads((artifacts / "metadata.json").read_text())
    assert meta["model_version"] == "test-1"
    assert meta["feature_names"] == FEATURE_NAMES
    assert len(meta["dataset_sha256"]) == 64
    metrics = meta["metrics"]
    # test window is the 91 days a forecast from val_end can serve
    assert metrics["test_window"] == {"first": "2017-10-01", "last": "2017-12-30"}
    assert set(metrics["baselines"]) == {"seasonal_naive", "moving_average_28"}


def test_model_beats_seasonal_naive_on_synthetic_data(artifacts: Path) -> None:
    metrics = json.loads((artifacts / "metrics.json").read_text())
    assert metrics["model"]["smape"] < metrics["baselines"]["seasonal_naive"]["smape"]


def test_history_and_reference_stats(artifacts: Path) -> None:
    with np.load(artifacts / "history.npz") as h:
        assert h["values"].shape == (6, HISTORY_DAYS)
        assert str(h["start"]) == "2016-11-27"  # 400 days ending 2017-12-31
    stats = json.loads((artifacts / "reference_stats.json").read_text())
    assert set(stats) == set(FEATURE_NAMES)
    for entry in stats.values():
        assert abs(sum(entry["proportions"]) - 1) < 1e-3


def test_drift_reference_describes_the_forecast_window(artifacts: Path) -> None:
    """The reference must match what the API computes for requests in the window
    it serves, so normal traffic is not reported as drift."""
    from datetime import date

    from app.model import ForecastModel
    from ml.drift_stats import feature_psi

    meta = json.loads((artifacts / "metadata.json").read_text())
    assert meta["drift_reference"] == {
        "basis": "forecast_window",
        "first": "2018-01-01",
        "last": "2018-04-01",
    }

    model = ForecastModel.load(artifacts)
    stats = json.loads((artifacts / "reference_stats.json").read_text())
    rng = np.random.default_rng(0)
    rows = []
    for _ in range(600):
        store, item = list(model.index)[rng.integers(len(model.index))]
        start = date(2018, 1, 1) + np.timedelta64(int(rng.integers(0, 91)), "D").item()
        rows.append(model.features(store, item, start, 1)[0])
    x = np.array(rows)
    for j, name in enumerate(FEATURE_NAMES):
        assert feature_psi(stats[name], x[:, j]) < 0.1, name
