"""FastAPI service: store-item demand forecasts up to 90 days ahead."""

from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app import logging_setup, telemetry
from app.model import ForecastModel, ForecastRangeError
from app.schemas import (
    BatchRequest,
    BatchResponse,
    DailyForecast,
    ForecastRequest,
    ForecastResponse,
    Health,
    ModelInfo,
)
from ml.features import FEATURE_NAMES

log = logging.getLogger("dfcast.api")
feature_log = logging.getLogger("dfcast.features")


_SOURCE_RE = re.compile(r"[a-z0-9-]{1,32}")


def traffic_source(request: Request) -> str:
    """Who sent the request: X-Traffic-Source (canary, smoke, drill, ...) or 'user'.

    Deploy tooling labels its synthetic traffic so the drift job can leave it
    out; anything malformed counts as user traffic.
    """
    value = request.headers.get("x-traffic-source", "").strip().lower()
    return value if _SOURCE_RE.fullmatch(value) else "user"


class State:
    model: ForecastModel | None = None
    ready: bool = False
    load_error: str | None = None


state = State()


def load_model(artifact_dir: str) -> None:
    """Load artifacts and run one warm-up prediction; sets readiness."""
    t0 = time.perf_counter()
    try:
        model = ForecastModel.load(artifact_dir)
        store, item = next(iter(model.index))
        model.forecast(store, item, model.last_servable, 1)  # warm-up
    except Exception as exc:  # readiness stays false; /readyz reports 503
        state.model, state.ready, state.load_error = None, False, repr(exc)
        log.exception("model load failed", extra={"artifact_dir": artifact_dir})
        return
    state.model, state.ready, state.load_error = model, True, None
    log.info(
        "model loaded",
        extra={
            "model_version": model.version,
            "model_load_seconds": round(time.perf_counter() - t0, 3),
            "servable_from": model.first_servable.isoformat(),
            "servable_to": model.last_servable.isoformat(),
        },
    )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    logging_setup.configure(os.environ.get("LOG_LEVEL", "INFO"))
    load_model(os.environ.get("ARTIFACT_DIR", "artifacts"))
    yield


TELEMETRY_ENABLED = telemetry.configure()

app = FastAPI(
    title="Demand Forecast API",
    version="1.0.0",
    description="Daily unit-sales forecasts for 10 stores x 50 items, up to 90 days ahead.",
    lifespan=lifespan,
)
if TELEMETRY_ENABLED:
    telemetry.instrument_app(app)


@app.middleware("http")
async def request_context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    request_id = request.headers.get("x-request-id") or uuid.uuid4().hex
    request.state.request_id = request_id
    request.state.traffic_source = traffic_source(request)
    t0 = time.perf_counter()
    try:
        response = await call_next(request)
    except Exception:
        log.exception("unhandled error", extra={"request_id": request_id, "path": request.url.path})
        response = JSONResponse(status_code=500, content={"detail": "internal error"})
    elapsed_ms = (time.perf_counter() - t0) * 1000
    response.headers["X-Request-ID"] = request_id
    if state.model is not None:
        response.headers["X-Model-Version"] = state.model.version
    if request.url.path.startswith("/v1/"):
        log.info(
            "request",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(elapsed_ms, 2),
                "model_version": state.model.version if state.model else None,
                "traffic_source": request.state.traffic_source,
            },
        )
    return response


def require_model() -> ForecastModel:
    if not state.ready or state.model is None:
        raise HTTPException(status_code=503, detail="model not loaded")
    return state.model


def range_error(loc: list[Any], message: str) -> HTTPException:
    """422 in the same shape FastAPI uses for validation errors."""
    return HTTPException(status_code=422, detail=[{"loc": loc, "msg": message, "type": "value_error"}])


def run_forecast(
    model: ForecastModel, req: ForecastRequest, loc: list[Any], request_id: str, source: str = "user"
) -> ForecastResponse:
    if not model.has_series(req.store, req.item):
        raise range_error([*loc, "item"], f"no history for store {req.store} item {req.item}")
    try:
        units, x = model.forecast(req.store, req.item, req.start_date, req.horizon_days)
    except ForecastRangeError as exc:
        raise range_error([*loc, "start_date"], str(exc)) from exc
    # one feature row per request (the first forecast day) feeds the drift job;
    # the vector travels as a JSON string so App Insights keeps it parseable
    features = dict(zip(FEATURE_NAMES, (round(float(v), 4) for v in x[0]), strict=True))
    feature_log.info(
        "forecast_features",
        extra={
            "request_id": request_id,
            "traffic_source": source,
            "model_version": model.version,
            "horizon_days": req.horizon_days,
            "store": req.store,
            "item": req.item,
            "features_json": json.dumps(features, separators=(",", ":")),
        },
    )
    telemetry.record_forecast(model.version, req.horizon_days, units)
    return ForecastResponse(
        store=req.store,
        item=req.item,
        model_version=model.version,
        forecast=[
            DailyForecast(date=req.start_date + timedelta(days=i), units=u) for i, u in enumerate(units)
        ],
    )


@app.post("/v1/forecast", response_model=ForecastResponse)
def forecast(req: ForecastRequest, request: Request) -> ForecastResponse:
    model = require_model()
    return run_forecast(model, req, ["body"], request.state.request_id, request.state.traffic_source)


@app.post("/v1/forecast/batch", response_model=BatchResponse)
def forecast_batch(batch: BatchRequest, request: Request) -> BatchResponse:
    model = require_model()
    source = request.state.traffic_source
    results = [
        run_forecast(model, req, ["body", "requests", i], request.state.request_id, source)
        for i, req in enumerate(batch.requests)
    ]
    return BatchResponse(model_version=model.version, results=results)


@app.get("/v1/model", response_model=ModelInfo)
def model_info() -> ModelInfo:
    model = require_model()
    meta = model.metadata
    metrics = meta["metrics"]
    return ModelInfo(
        model_version=model.version,
        git_sha=meta["git_sha"],
        trained_at=meta["trained_at"],
        test_smape=metrics["model"]["smape"],
        test_mae=metrics["model"]["mae"],
        baseline_seasonal_naive_smape=metrics["baselines"]["seasonal_naive"]["smape"],
        history_end=model.history_end,
        servable_from=model.first_servable,
        servable_to=model.last_servable,
    )


@app.get("/healthz", response_model=Health)
def healthz() -> Health:
    return Health(status="ok")


@app.get("/readyz", response_model=Health, responses={503: {"model": Health}})
def readyz() -> Any:
    if state.ready:
        return Health(status="ready")
    return JSONResponse(status_code=503, content={"status": "not ready"})
