"""Fixed canary inputs and the checks a newly deployed revision must pass.

Training writes ``canary_reference.json``: 20 fixed store-item requests, the
predictions the trained model produced for them, and the seasonal-naive values
for the same days. After deploy, the smoke test sends the same requests to the
canary revision and checks two things:

1. **Consistency**: predictions match what training produced. A mismatch means
   the image does not contain the model we think it does (packaging bug, wrong
   artifacts, feature code drift between training and serving).
2. **Plausibility**: predictions are close enough to seasonal naive (SMAPE
   below a bound calibrated on real models). This catches a model that is
   internally consistent but nonsense, such as the constant-output model used
   in the bad-model drill. A 200 OK alone would not catch it.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import lightgbm as lgb
import numpy as np

from ml.data import Panel
from ml.features import build_matrix
from ml.metrics import smape

N_INPUTS = 20
HORIZON = 7
CONSISTENCY_TOLERANCE = 0.02  # units; responses are rounded to 0.01
PLAUSIBILITY_MAX_SMAPE = 35.0  # vs seasonal naive; real model ~14, constant model ~53


def build_reference(booster: lgb.Booster, panel: Panel, seed: int = 0) -> dict[str, Any]:
    rng = np.random.default_rng(seed)
    rows = rng.choice(panel.values.shape[0], size=min(N_INPUTS, panel.values.shape[0]), replace=False)
    start = panel.end + timedelta(days=1)
    positions = np.arange(panel.n_days, panel.n_days + HORIZON)
    cases = []
    for r in sorted(rows.tolist()):
        x = build_matrix(
            panel.values[r : r + 1],
            panel.start,
            panel.stores[r : r + 1],
            panel.items[r : r + 1],
            positions,
        )
        expected = np.clip(np.expm1(booster.predict(x)), 0.0, None)
        naive = panel.values[r, positions - 364]
        cases.append(
            {
                "request": {
                    "store": int(panel.stores[r]),
                    "item": int(panel.items[r]),
                    "start_date": start.isoformat(),
                    "horizon_days": HORIZON,
                },
                "expected": [round(float(v), 2) for v in expected],
                "seasonal_naive": [float(v) for v in naive],
            }
        )
    expected_all = np.array([c["expected"] for c in cases])
    naive_all = np.array([c["seasonal_naive"] for c in cases])
    return {
        "cases": cases,
        "model_smape_vs_seasonal_naive": round(smape(naive_all, expected_all), 3),
        "plausibility_max_smape": PLAUSIBILITY_MAX_SMAPE,
        "consistency_tolerance": CONSISTENCY_TOLERANCE,
    }


def check(reference: dict[str, Any], served: list[list[float]]) -> list[str]:
    """Compare served predictions (one list per case) with the reference.

    Returns a list of failure messages; empty means the revision passes.
    """
    failures: list[str] = []
    cases = reference["cases"]
    if len(served) != len(cases):
        return [f"expected {len(cases)} responses, got {len(served)}"]
    tol = reference.get("consistency_tolerance", CONSISTENCY_TOLERANCE)
    for case, got in zip(cases, served, strict=True):
        exp = case["expected"]
        if len(got) != len(exp):
            failures.append(f"{case['request']}: {len(got)} days returned, expected {len(exp)}")
            continue
        worst = float(np.max(np.abs(np.asarray(got) - np.asarray(exp))))
        if worst > tol:
            failures.append(f"{case['request']}: differs from training output by up to {worst:.3f} units")
    naive = np.array([c["seasonal_naive"] for c in cases])
    got_all = np.array(served, dtype=float) if not failures else None
    if got_all is not None:
        score = smape(naive, got_all)
        limit = reference.get("plausibility_max_smape", PLAUSIBILITY_MAX_SMAPE)
        if score > limit:
            failures.append(f"SMAPE vs seasonal naive is {score:.1f}, above the plausibility limit {limit}")
    return failures


def plausibility_only(reference: dict[str, Any], served: list[list[float]]) -> list[str]:
    """Plausibility check alone (used when comparing against a different model)."""
    naive = np.array([c["seasonal_naive"] for c in reference["cases"]])
    score = smape(naive, np.array(served, dtype=float))
    limit = reference.get("plausibility_max_smape", PLAUSIBILITY_MAX_SMAPE)
    return [] if score <= limit else [f"SMAPE vs seasonal naive {score:.1f} > {limit}"]
