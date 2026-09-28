"""Train, evaluate and package the demand forecasting model.

Usage:
    python -m ml.train --data data/raw/train.csv --out artifacts

Evaluation is honest about the 91-day lag: for validation and test, the
history is cut at the forecast origin, and each window covers the 91 days a
real forecast from that origin could serve. The model that ships is the one
the reported test metrics describe.

Outputs (all in --out):
    model.txt             LightGBM model
    metadata.json         version, git SHA, dataset hash, params, metrics
    metrics.json          test metrics for the model and baselines
    reference_stats.json  per-feature histograms for the drift job
    canary_reference.json fixed requests + expected outputs for post-deploy smoke tests
    history.npz           recent sales per series, used by the API for features
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from ml import canary
from ml import data as data_mod
from ml.drift_stats import reference_stats
from ml.features import (
    CATEGORICAL_FEATURES,
    FEATURE_NAMES,
    MAX_LOOKBACK,
    MIN_LAG,
    build_matrix,
)
from ml.metrics import score

log = logging.getLogger("ml.train")

HISTORY_DAYS = 400  # days of history shipped with the model (>= MAX_LOOKBACK + 1)

DEFAULT_PARAMS: dict[str, Any] = {
    "objective": "regression_l1",
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_data_in_leaf": 100,
    "feature_fraction": 0.8,
    "bagging_fraction": 0.8,
    "bagging_freq": 1,
    "lambda_l2": 1.0,
    "verbosity": -1,
    "seed": 42,
    "deterministic": True,
    "force_row_wise": True,
}


@dataclass(frozen=True)
class Splits:
    train_end: date = date(2017, 6, 30)
    val_end: date = date(2017, 9, 30)


def git_sha() -> str:
    env = os.environ.get("GITHUB_SHA")
    if env:
        return env
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def window_positions(panel: data_mod.Panel, first: date, last: date) -> np.ndarray:
    return np.arange(panel.position(first), panel.position(last) + 1)


def features_and_target(
    panel: data_mod.Panel, first: date, last: date, origin: date | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Feature rows for target days [first, last].

    If ``origin`` is given, history after ``origin`` is hidden from the
    features (the targets still come from the full panel).
    """
    positions = window_positions(panel, first, last)
    values = panel.values
    if origin is not None:
        values = values.copy()
        values[:, panel.position(origin) + 1 :] = np.nan
    x = build_matrix(values, panel.start, panel.stores, panel.items, positions)
    y = panel.values[:, positions].reshape(-1)
    return x, y


def forecast_window(origin: date, panel_end: date) -> tuple[date, date]:
    """The days a forecast made at ``origin`` can serve: origin+1 .. origin+91."""
    last = min(origin + timedelta(days=MIN_LAG), panel_end)
    return origin + timedelta(days=1), last


def baselines(panel: data_mod.Panel, first: date, last: date, origin: date) -> dict[str, dict]:
    positions = window_positions(panel, first, last)
    actual = panel.values[:, positions]
    seasonal_naive = panel.values[:, positions - 364]
    o = panel.position(origin)
    ma28 = panel.values[:, o - 27 : o + 1].mean(axis=1, keepdims=True)
    ma28 = np.repeat(ma28, positions.size, axis=1)
    return {
        "seasonal_naive": score(actual, seasonal_naive),
        "moving_average_28": score(actual, ma28),
    }


def to_target(y: np.ndarray) -> np.ndarray:
    return np.log1p(y)


def from_target(z: np.ndarray) -> np.ndarray:
    return np.clip(np.expm1(z), 0.0, None)


def dataset(x: np.ndarray, y: np.ndarray, reference: lgb.Dataset | None = None) -> lgb.Dataset:
    return lgb.Dataset(
        x,
        label=to_target(y),
        feature_name=FEATURE_NAMES,
        categorical_feature=CATEGORICAL_FEATURES,
        reference=reference,
        free_raw_data=False,
    )


def train(
    panel: data_mod.Panel,
    splits: Splits,
    params: dict[str, Any] | None = None,
    max_rounds: int = 3000,
    early_stopping: int = 100,
) -> tuple[lgb.Booster, dict[str, Any], np.ndarray]:
    """Fit with early stopping on validation, refit through val_end, score test.

    Returns the final booster, a metrics dict and the final training features
    (used for drift reference statistics).
    """
    params = {**DEFAULT_PARAMS, **(params or {})}
    first_trainable = panel.start + timedelta(days=MAX_LOOKBACK)

    # 1) fit on train, early-stop on validation
    x_tr, y_tr = features_and_target(panel, first_trainable, splits.train_end)
    val_first, val_last = forecast_window(splits.train_end, panel.end)
    x_va, y_va = features_and_target(panel, val_first, val_last, origin=splits.train_end)
    d_tr = dataset(x_tr, y_tr)
    d_va = dataset(x_va, y_va, reference=d_tr)
    t0 = time.perf_counter()
    booster = lgb.train(
        params,
        d_tr,
        num_boost_round=max_rounds,
        valid_sets=[d_va],
        valid_names=["val"],
        callbacks=[lgb.early_stopping(early_stopping, verbose=False)],
    )
    best_iter = booster.best_iteration or max_rounds
    val_pred = from_target(np.asarray(booster.predict(x_va, num_iteration=best_iter)))
    val_metrics = score(y_va, val_pred)
    log.info("validation: best_iter=%d %s (%.1fs)", best_iter, val_metrics, time.perf_counter() - t0)

    # 2) refit on train + validation with the chosen number of rounds
    x_full, y_full = features_and_target(panel, first_trainable, splits.val_end)
    final = lgb.train(params, dataset(x_full, y_full), num_boost_round=best_iter)

    # 3) score the final model on the test window
    test_first, test_last = forecast_window(splits.val_end, panel.end)
    x_te, y_te = features_and_target(panel, test_first, test_last, origin=splits.val_end)
    test_pred = from_target(np.asarray(final.predict(x_te)))
    model_metrics = score(y_te, test_pred)
    base = baselines(panel, test_first, test_last, splits.val_end)
    log.info("test: model=%s baselines=%s", model_metrics, base)

    metrics = {
        "test_window": {"first": test_first.isoformat(), "last": test_last.isoformat()},
        "validation": {**val_metrics, "best_iteration": best_iter},
        "model": model_metrics,
        "baselines": base,
        "rows": {"train": len(y_tr), "final_fit": len(y_full), "test": len(y_te)},
    }
    return final, metrics, x_full


def save_history(panel: data_mod.Panel, path: Path, days: int = HISTORY_DAYS) -> None:
    first = panel.end - timedelta(days=days - 1)
    recent = panel.slice_days(first, panel.end)
    np.savez_compressed(
        path,
        values=recent.values.astype(np.float32),
        start=np.array(recent.start.isoformat()),
        stores=recent.stores.astype(np.int16),
        items=recent.items.astype(np.int16),
    )


def run(
    data_path: Path,
    out: Path,
    model_version: str | None,
    splits: Splits,
    params: dict,
    max_rounds: int = 3000,
) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    panel = data_mod.to_panel(data_mod.load_csv(data_path))
    log.info("panel: %d series, %s..%s", panel.values.shape[0], panel.start, panel.end)

    booster, metrics, x_full = train(panel, splits, params, max_rounds=max_rounds)
    sha = git_sha()
    now = datetime.now(timezone.utc)
    version = model_version or f"{now:%Y%m%d.%H%M}-{sha[:7]}"

    booster.save_model(str(out / "model.txt"))
    save_history(panel, out / "history.npz")
    stats = reference_stats(x_full, FEATURE_NAMES, CATEGORICAL_FEATURES)
    (out / "reference_stats.json").write_text(json.dumps(stats, indent=2))
    (out / "metrics.json").write_text(json.dumps(metrics, indent=2))
    reference = canary.build_reference(booster, panel)
    (out / "canary_reference.json").write_text(json.dumps(reference, indent=2))
    metadata = {
        "model_version": version,
        "git_sha": sha,
        "trained_at": now.isoformat(timespec="seconds"),
        "dataset_sha256": data_mod.file_sha256(data_path),
        "data_range": {"first": panel.start.isoformat(), "last": panel.end.isoformat()},
        "splits": {"train_end": splits.train_end.isoformat(), "val_end": splits.val_end.isoformat()},
        "feature_names": FEATURE_NAMES,
        "target_transform": "log1p",
        "params": {**DEFAULT_PARAMS, **params},
        "num_trees": booster.num_trees(),
        "metrics": metrics,
    }
    (out / "metadata.json").write_text(json.dumps(metadata, indent=2))
    log.info("wrote artifacts for %s to %s", version, out)
    return metadata


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--data", type=Path, default=Path("data/raw/train.csv"))
    p.add_argument("--out", type=Path, default=Path("artifacts"))
    p.add_argument("--model-version", default=os.environ.get("MODEL_VERSION"))
    p.add_argument("--train-end", type=date.fromisoformat, default=Splits.train_end)
    p.add_argument("--val-end", type=date.fromisoformat, default=Splits.val_end)
    p.add_argument("--params", type=json.loads, default={}, help="JSON overrides for LightGBM params")
    p.add_argument("--max-rounds", type=int, default=3000)
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    meta = run(
        args.data,
        args.out,
        args.model_version,
        Splits(args.train_end, args.val_end),
        args.params,
        args.max_rounds,
    )
    print(json.dumps({"model_version": meta["model_version"], **meta["metrics"]}, indent=2))


if __name__ == "__main__":
    main()
