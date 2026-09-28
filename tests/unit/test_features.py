from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from ml.features import (
    FEATURE_NAMES,
    HISTORY_FEATURES,
    MAX_LOOKBACK,
    MIN_LAG,
    build_matrix,
    calendar_features,
    history_features,
)


@pytest.fixture
def series() -> np.ndarray:
    return np.random.default_rng(0).poisson(20, (3, 800)).astype(float)


def naive_features(s: pd.Series, p: int) -> list[float]:
    window28 = s[p - 118 : p - 90]
    return [
        s[p - 91],
        s[p - 364],
        window28.mean(),
        window28.std(),
        s[p - 181 : p - 90].mean(),
        s[[p - lag for lag in range(91, 365, 7)]].mean(),
    ]


@pytest.mark.parametrize("position", [364, 500, 799, 850, 890])
def test_history_features_match_naive_pandas(series: np.ndarray, position: int) -> None:
    got = history_features(series, np.array([position]))[1, 0]
    expected = naive_features(pd.Series(series[1]), position)
    np.testing.assert_allclose(got, expected, rtol=1e-9)
    assert got.shape == (len(HISTORY_FEATURES),)


def test_features_ignore_the_last_91_days(series: np.ndarray) -> None:
    """No leakage: data within 91 days of the target must not change features."""
    position = 700
    tampered = series.copy()
    tampered[:, position - MIN_LAG + 1 :] = np.nan
    np.testing.assert_array_equal(
        history_features(series, np.array([position])),
        history_features(tampered, np.array([position])),
    )


def test_future_positions_are_supported(series: np.ndarray) -> None:
    last_ok = series.shape[1] - 1 + MIN_LAG
    feats = history_features(series, np.array([last_ok]))
    assert np.isfinite(feats).all()


@pytest.mark.parametrize("position", [MAX_LOOKBACK - 1, 800 + MIN_LAG])
def test_positions_outside_window_raise(series: np.ndarray, position: int) -> None:
    with pytest.raises(ValueError, match="outside the usable history"):
        history_features(series, np.array([position]))


def test_calendar_matches_pandas() -> None:
    dates = pd.date_range("2016-12-25", "2018-01-10", freq="D")
    got = calendar_features(dates.to_numpy().astype("datetime64[D]"))
    iso = dates.isocalendar()
    expected = np.column_stack(
        [
            dates.dayofweek,
            dates.day,
            dates.month,
            iso.week,
            dates.dayofyear,
            dates.year,
            (dates.dayofweek >= 5).astype(int),
        ]
    )
    np.testing.assert_array_equal(got, expected)


def test_build_matrix_layout(series: np.ndarray) -> None:
    positions = np.arange(400, 410)
    x = build_matrix(series, date(2015, 1, 1), np.array([1, 1, 2]), np.array([5, 6, 5]), positions)
    assert x.shape == (3 * len(positions), len(FEATURE_NAMES))
    # series-major: first block is series 0
    assert (x[: len(positions), 0] == 1).all() and (x[: len(positions), 1] == 5).all()
    assert (x[-len(positions) :, 0] == 2).all()
    lag91_col = FEATURE_NAMES.index("lag_91")
    np.testing.assert_array_equal(x[: len(positions), lag91_col], series[0, positions - 91])
