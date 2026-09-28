from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ml.data import to_panel
from ml.drift_stats import feature_psi, psi, reference_stats


@pytest.fixture
def ref() -> dict:
    rng = np.random.default_rng(1)
    x = np.column_stack([rng.integers(1, 11, 20_000), rng.normal(50, 10, 20_000)])
    return reference_stats(x, ["store", "lag_91"], ["store"])


def test_psi_identical_is_zero() -> None:
    p = np.array([0.2, 0.3, 0.5])
    assert psi(p, p) == pytest.approx(0.0)


def test_same_distribution_is_stable(ref: dict) -> None:
    rng = np.random.default_rng(2)
    assert feature_psi(ref["lag_91"], rng.normal(50, 10, 5_000)) < 0.1
    assert feature_psi(ref["store"], rng.integers(1, 11, 5_000)) < 0.1


def test_shifted_distribution_alerts(ref: dict) -> None:
    rng = np.random.default_rng(3)
    assert feature_psi(ref["lag_91"], rng.normal(70, 10, 5_000)) > 0.25
    assert feature_psi(ref["store"], np.full(5_000, 3)) > 0.25


def test_unseen_category_alerts(ref: dict) -> None:
    assert feature_psi(ref["store"], np.full(1_000, 99)) > 0.25


def test_to_panel_rejects_gaps_and_duplicates() -> None:
    df = pd.DataFrame(
        {
            "date": pd.to_datetime(["2017-01-01", "2017-01-02", "2017-01-01", "2017-01-02"]),
            "store": [1, 1, 1, 1],
            "item": [1, 1, 2, 2],
            "sales": [1, 2, 3, 4],
        }
    )
    panel = to_panel(df)
    assert panel.values.shape == (2, 2)
    with pytest.raises(ValueError, match="duplicate"):
        to_panel(pd.concat([df, df.iloc[:1]]))
    with pytest.raises(ValueError, match="missing days"):
        to_panel(df.drop(index=1))
