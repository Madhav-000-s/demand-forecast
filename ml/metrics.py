"""Forecast accuracy metrics."""

from __future__ import annotations

import numpy as np


def smape(actual: np.ndarray, forecast: np.ndarray) -> float:
    """Symmetric MAPE in percent (0-200), as scored in the Kaggle competition.

    Terms where both actual and forecast are zero count as zero error.
    """
    a = np.asarray(actual, dtype=np.float64).ravel()
    f = np.asarray(forecast, dtype=np.float64).ravel()
    denom = np.abs(a) + np.abs(f)
    terms = np.where(denom == 0, 0.0, 2.0 * np.abs(f - a) / np.where(denom == 0, 1.0, denom))
    return float(100.0 * terms.mean())


def mae(actual: np.ndarray, forecast: np.ndarray) -> float:
    a = np.asarray(actual, dtype=np.float64).ravel()
    f = np.asarray(forecast, dtype=np.float64).ravel()
    return float(np.mean(np.abs(f - a)))


def score(actual: np.ndarray, forecast: np.ndarray) -> dict[str, float]:
    return {"smape": round(smape(actual, forecast), 4), "mae": round(mae(actual, forecast), 4)}
