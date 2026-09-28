"""Loading the Kaggle store-item sales file into a dense (series x day) panel."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Panel:
    """Daily sales for every store-item series on one shared date axis."""

    values: np.ndarray  # (n_series, T) float64
    start: date  # date of column 0
    stores: np.ndarray  # (n_series,) int
    items: np.ndarray  # (n_series,) int

    @property
    def n_days(self) -> int:
        return int(self.values.shape[1])

    @property
    def end(self) -> date:
        return (np.datetime64(self.start, "D") + self.n_days - 1).astype(date)

    def position(self, d: date) -> int:
        return int((np.datetime64(d, "D") - np.datetime64(self.start, "D")).astype(int))

    def slice_days(self, first: date, last: date) -> Panel:
        """Panel restricted to [first, last]."""
        lo, hi = self.position(first), self.position(last)
        if lo < 0 or hi >= self.n_days or lo > hi:
            raise ValueError(f"range {first}..{last} not inside {self.start}..{self.end}")
        return Panel(self.values[:, lo : hi + 1], first, self.stores, self.items)


def load_csv(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=["date"])
    expected = {"date", "store", "item", "sales"}
    missing = expected - set(df.columns)
    if missing:
        raise ValueError(f"{path} is missing columns: {sorted(missing)}")
    return df


def to_panel(df: pd.DataFrame) -> Panel:
    """Pivot long rows into a dense panel. Fails on gaps or duplicate rows."""
    if df.duplicated(["date", "store", "item"]).any():
        raise ValueError("duplicate (date, store, item) rows")
    wide = df.pivot_table(
        index=["store", "item"], columns="date", values="sales", aggfunc="first"
    ).sort_index()
    full_range = pd.date_range(wide.columns.min(), wide.columns.max(), freq="D")
    wide = wide.reindex(columns=full_range)
    if wide.isna().any().any():
        raise ValueError("panel has missing days; every series needs every date")
    stores = wide.index.get_level_values("store").to_numpy(dtype=int)
    items = wide.index.get_level_values("item").to_numpy(dtype=int)
    return Panel(
        values=wide.to_numpy(dtype=np.float64),
        start=full_range[0].date(),
        stores=stores,
        items=items,
    )


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
