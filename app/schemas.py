"""Request and response models for the forecast API."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, ConfigDict, Field

from ml.features import MAX_HORIZON

MAX_BATCH = 50


class ForecastRequest(BaseModel):
    store: int = Field(ge=1, le=10, description="Store id, 1-10")
    item: int = Field(ge=1, le=50, description="Item id, 1-50")
    start_date: date = Field(description="First day to forecast (ISO date)")
    horizon_days: int = Field(ge=1, le=MAX_HORIZON, description="Number of days to forecast, 1-90")

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "examples": [{"store": 3, "item": 17, "start_date": "2018-01-01", "horizon_days": 14}]
        },
    )


class DailyForecast(BaseModel):
    date: date
    units: float


class ForecastResponse(BaseModel):
    store: int
    item: int
    model_version: str
    forecast: list[DailyForecast]


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requests: list[ForecastRequest] = Field(min_length=1, max_length=MAX_BATCH)


class BatchResponse(BaseModel):
    model_version: str
    results: list[ForecastResponse]


class ModelInfo(BaseModel):
    model_version: str
    git_sha: str
    trained_at: str
    test_smape: float
    test_mae: float
    baseline_seasonal_naive_smape: float
    history_end: date
    servable_from: date
    servable_to: date


class Health(BaseModel):
    status: str
