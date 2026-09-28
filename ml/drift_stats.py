"""Reference distributions and Population Stability Index for drift checks.

Training writes ``reference_stats.json`` with one histogram per feature; the
drift job later bins recent request features with the same edges and compares.
"""

from __future__ import annotations

from typing import Any

import numpy as np

N_BINS = 10
EPS = 1e-4  # floor for empty bins so PSI stays finite


def reference_stats(features: np.ndarray, names: list[str], categorical: list[str]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for j, name in enumerate(names):
        col = features[:, j]
        col = col[~np.isnan(col)]
        if name in categorical:
            cats, counts = np.unique(col.astype(int), return_counts=True)
            stats[name] = {
                "type": "categorical",
                "categories": cats.tolist(),
                "proportions": (counts / counts.sum()).round(6).tolist(),
            }
        else:
            edges = np.unique(np.quantile(col, np.linspace(0, 1, N_BINS + 1)))
            counts = bin_counts(col, edges)
            stats[name] = {
                "type": "numeric",
                "edges": edges.round(6).tolist(),
                "proportions": (counts / counts.sum()).round(6).tolist(),
            }
    return stats


def bin_counts(values: np.ndarray, edges: np.ndarray) -> np.ndarray:
    """Counts per bin; values outside the reference range go to the end bins."""
    inner = np.asarray(edges)[1:-1]
    idx = np.searchsorted(inner, values, side="right")
    return np.bincount(idx, minlength=len(edges) - 1).astype(np.float64)


def psi(expected: np.ndarray, actual: np.ndarray) -> float:
    """Population Stability Index between two proportion vectors."""
    e = np.clip(np.asarray(expected, dtype=np.float64), EPS, None)
    a = np.clip(np.asarray(actual, dtype=np.float64), EPS, None)
    e, a = e / e.sum(), a / a.sum()
    return float(np.sum((a - e) * np.log(a / e)))


def feature_psi(ref: dict[str, Any], values: np.ndarray) -> float:
    """PSI of new observations of one feature against its reference entry."""
    values = np.asarray(values, dtype=np.float64)
    values = values[~np.isnan(values)]
    if values.size == 0:
        return 0.0
    if ref["type"] == "categorical":
        cats = np.asarray(ref["categories"])
        counts = np.array([(values.astype(int) == c).sum() for c in cats], dtype=np.float64)
        unseen = values.size - counts.sum()
        if unseen:  # unseen categories get their own bucket with ~0 expected mass
            return psi(np.append(ref["proportions"], 0.0), np.append(counts, unseen) / values.size)
        return psi(np.asarray(ref["proportions"]), counts / values.size)
    counts = bin_counts(values, np.asarray(ref["edges"]))
    return psi(np.asarray(ref["proportions"]), counts / counts.sum())
