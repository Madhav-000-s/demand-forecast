"""Feature builder shared by training and serving.

Every history feature is lagged by at least ``MIN_LAG`` (91) days, so a model
trained on these features can forecast any day up to 91 days past the last
observed date directly, without feeding its own predictions back in.

The same function builds features for training rows and for API requests,
which is what keeps training and serving consistent.
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np

MIN_LAG = 91  # smallest history lag used by any feature
MAX_LOOKBACK = 364  # oldest day any feature reads, relative to the target day
MAX_HORIZON = 90

CATEGORICAL_FEATURES = ["store", "item"]
CALENDAR_FEATURES = [
    "dayofweek",
    "day",
    "month",
    "weekofyear",
    "dayofyear",
    "year",
    "is_weekend",
]
HISTORY_FEATURES = [
    "lag_91",
    "lag_364",
    "roll28_mean_91",
    "roll28_std_91",
    "roll91_mean_91",
    "dow_mean_1y",
]
FEATURE_NAMES = CATEGORICAL_FEATURES + CALENDAR_FEATURES + HISTORY_FEATURES


def calendar_features(dates: np.ndarray) -> np.ndarray:
    """Calendar features for an array of ``datetime64[D]`` values -> (n, 7)."""
    d = dates.astype("datetime64[D]")
    years = d.astype("datetime64[Y]")
    months = d.astype("datetime64[M]")
    year = years.astype(int) + 1970
    month = (months - years).astype(int) + 1
    day = (d - months).astype(int) + 1
    dayofyear = (d - years).astype(int) + 1
    # 1970-01-01 was a Thursday; Monday = 0 like pandas
    dayofweek = (d.astype(int) + 3) % 7
    # ISO week number
    thursday = d + (3 - dayofweek).astype("timedelta64[D]")
    iso_year_start = thursday.astype("datetime64[Y]")
    weekofyear = (thursday - iso_year_start).astype(int) // 7 + 1
    is_weekend = (dayofweek >= 5).astype(int)
    return np.column_stack([dayofweek, day, month, weekofyear, dayofyear, year, is_weekend]).astype(
        np.float64
    )


def history_features(values: np.ndarray, positions: np.ndarray) -> np.ndarray:
    """History features for target positions in one or more series.

    Args:
        values: sales, shape ``(n_series, T)``; column ``t`` is day ``t`` of the
            history window. NaN is allowed only where no feature reads it.
        positions: integer target positions on the same time axis, shape
            ``(n,)``. A position may be past the end of the history (that is a
            future day) as long as ``position - MIN_LAG < T``, and it must
            satisfy ``position - MAX_LOOKBACK >= 0``.

    Returns:
        Array of shape ``(n_series, n, len(HISTORY_FEATURES))``.
    """
    values = np.asarray(values, dtype=np.float64)
    positions = np.asarray(positions, dtype=np.int64)
    if values.ndim != 2:
        raise ValueError("values must be 2-D (n_series, T)")
    n_time = values.shape[1]
    if positions.size and (positions.min() - MAX_LOOKBACK < 0 or positions.max() - MIN_LAG >= n_time):
        raise ValueError("target positions fall outside the usable history window")

    # prefix sums give O(1) rolling windows
    zeros = np.zeros((values.shape[0], 1))
    cs = np.concatenate([zeros, np.cumsum(values, axis=1)], axis=1)
    cs2 = np.concatenate([zeros, np.cumsum(values**2, axis=1)], axis=1)

    def window_sum(prefix: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
        """Sum over inclusive positions [lo, hi]."""
        return prefix[:, hi + 1] - prefix[:, lo]

    end = positions - MIN_LAG  # most recent usable day
    lag_91 = values[:, end]
    lag_364 = values[:, positions - 364]

    s28 = window_sum(cs, end - 27, end)
    ss28 = window_sum(cs2, end - 27, end)
    roll28_mean = s28 / 28.0
    roll28_var = np.maximum(ss28 / 28.0 - roll28_mean**2, 0.0) * 28.0 / 27.0
    roll28_std = np.sqrt(roll28_var)

    roll91_mean = window_sum(cs, end - 90, end) / 91.0

    # same weekday over the prior year: lags 91, 98, ..., 364 (91 = 13 weeks)
    weekly_lags = np.arange(MIN_LAG, MAX_LOOKBACK + 1, 7)
    dow_mean = np.mean(np.stack([values[:, positions - lag] for lag in weekly_lags], axis=0), axis=0)

    return np.stack([lag_91, lag_364, roll28_mean, roll28_std, roll91_mean, dow_mean], axis=-1)


def build_matrix(
    values: np.ndarray,
    history_start: date,
    stores: np.ndarray,
    items: np.ndarray,
    positions: np.ndarray,
) -> np.ndarray:
    """Full feature matrix, one row per (series, position), series-major.

    ``stores`` and ``items`` give the id of each row of ``values``.
    Column order is ``FEATURE_NAMES``.
    """
    positions = np.asarray(positions, dtype=np.int64)
    n_series, n_pos = values.shape[0], positions.size
    target_dates = np.datetime64(history_start, "D") + positions
    cal = calendar_features(target_dates)  # (n_pos, 7)
    hist = history_features(values, positions)  # (n_series, n_pos, 6)

    ids = np.column_stack([np.repeat(np.asarray(stores), n_pos), np.repeat(np.asarray(items), n_pos)]).astype(
        np.float64
    )
    cal_rep = np.tile(cal, (n_series, 1))
    return np.hstack([ids, cal_rep, hist.reshape(n_series * n_pos, -1)])


def dates_for(start: date, horizon_days: int) -> list[date]:
    return [start + timedelta(days=i) for i in range(horizon_days)]
