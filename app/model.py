"""Loads model artifacts and turns forecast requests into predictions."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import lightgbm as lgb
import numpy as np

from ml.features import FEATURE_NAMES, MAX_LOOKBACK, MIN_LAG, build_matrix


class ForecastRangeError(ValueError):
    """Requested dates fall outside what the shipped history can support."""


@dataclass
class ForecastModel:
    booster: lgb.Booster
    metadata: dict[str, Any]
    history: np.ndarray  # (n_series, T)
    history_start: date
    index: dict[tuple[int, int], int]  # (store, item) -> row in history

    @property
    def version(self) -> str:
        return str(self.metadata["model_version"])

    @property
    def history_end(self) -> date:
        return self.history_start + timedelta(days=self.history.shape[1] - 1)

    @property
    def first_servable(self) -> date:
        return self.history_start + timedelta(days=MAX_LOOKBACK)

    @property
    def last_servable(self) -> date:
        return self.history_end + timedelta(days=MIN_LAG)

    @classmethod
    def load(cls, artifact_dir: str | Path) -> ForecastModel:
        d = Path(artifact_dir)
        metadata = json.loads((d / "metadata.json").read_text())
        if metadata.get("feature_names") != FEATURE_NAMES:
            raise RuntimeError("model was trained with a different feature set than this code builds")
        booster = lgb.Booster(model_file=str(d / "model.txt"))
        with np.load(d / "history.npz") as h:
            values = h["values"].astype(np.float64)
            start = date.fromisoformat(str(h["start"]))
            stores, items = h["stores"].astype(int), h["items"].astype(int)
        index = {(int(s), int(i)): r for r, (s, i) in enumerate(zip(stores, items, strict=True))}
        return cls(booster, metadata, values, start, index)

    def has_series(self, store: int, item: int) -> bool:
        return (store, item) in self.index

    def features(self, store: int, item: int, start: date, horizon_days: int) -> np.ndarray:
        last = start + timedelta(days=horizon_days - 1)
        if start < self.first_servable or last > self.last_servable:
            raise ForecastRangeError(
                f"forecast dates must fall within {self.first_servable.isoformat()}"
                f"..{self.last_servable.isoformat()}"
            )
        row = self.index[(store, item)]
        first_pos = (start - self.history_start).days
        positions = np.arange(first_pos, first_pos + horizon_days)
        return build_matrix(
            self.history[row : row + 1],
            self.history_start,
            np.array([store]),
            np.array([item]),
            positions,
        )

    def predict_features(self, x: np.ndarray) -> np.ndarray:
        return np.clip(np.expm1(self.booster.predict(x)), 0.0, None)

    def forecast(
        self, store: int, item: int, start: date, horizon_days: int
    ) -> tuple[list[float], np.ndarray]:
        """Returns (units per day, feature matrix used)."""
        x = self.features(store, item, start, horizon_days)
        units = self.predict_features(x)
        return [round(float(u), 2) for u in units], x
