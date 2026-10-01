"""OpenTelemetry export to Application Insights.

Enabled only when APPLICATIONINSIGHTS_CONNECTION_STRING is set, so local runs
and tests stay offline. Each replica reports the Container Apps revision it
belongs to (as ``service.version``) and its replica name (as
``service.instance.id``, which App Insights shows as ``cloud_RoleInstance``).
The canary analysis in the deploy workflow filters requests by revision.

Custom metrics (App Insights ``customMetrics``) come from the OpenTelemetry
metrics API. Without a configured provider the instruments are no-ops, so the
API code records them unconditionally.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import metrics

log = logging.getLogger("dfcast.telemetry")

_meter = metrics.get_meter("dfcast.api")
FORECASTS = _meter.create_counter(
    "dfcast_forecasts", unit="1", description="Forecasts served, by model version and horizon bucket"
)
RATE_LIMITED = _meter.create_counter(
    "dfcast_rate_limited", unit="1", description="Requests rejected with 429 by the per-client rate limit"
)
PREDICTED_UNITS = _meter.create_histogram(
    "dfcast_predicted_units",
    unit="units",
    description="Mean predicted daily units per forecast; a shift here is prediction drift",
)


def horizon_bucket(days: int) -> str:
    """Low-cardinality label for metrics: 1-7, 8-30, 31-90."""
    if days <= 7:
        return "1-7"
    return "8-30" if days <= 30 else "31-90"


def record_forecast(model_version: str, horizon_days: int, units: list[float]) -> None:
    FORECASTS.add(1, {"model_version": model_version, "horizon_bucket": horizon_bucket(horizon_days)})
    if units:
        PREDICTED_UNITS.record(sum(units) / len(units), {"model_version": model_version})


def resource_attributes() -> dict[str, str]:
    revision = os.environ.get("CONTAINER_APP_REVISION", "local")
    replica = os.environ.get("CONTAINER_APP_REPLICA_NAME", os.environ.get("HOSTNAME", "local"))
    return {
        "service.name": os.environ.get("OTEL_SERVICE_NAME", "dfcast-api"),
        "service.version": revision,
        "service.instance.id": replica,
    }


def configure() -> bool:
    """Set up Azure Monitor export. Returns True if telemetry is enabled."""
    if not os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING"):
        log.info("telemetry disabled: no APPLICATIONINSIGHTS_CONNECTION_STRING")
        return False
    from azure.monitor.opentelemetry import configure_azure_monitor
    from opentelemetry.sdk.resources import Resource

    configure_azure_monitor(
        resource=Resource.create(resource_attributes()),
        logger_name="dfcast",  # export our own loggers, not uvicorn's
        enable_live_metrics=False,
    )
    log.info("telemetry enabled", extra={k.replace(".", "_"): v for k, v in resource_attributes().items()})
    return True


def instrument_app(app: Any) -> None:
    """Trace incoming requests. Probe endpoints are excluded to save ingestion."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
