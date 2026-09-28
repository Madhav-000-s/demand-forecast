"""OpenTelemetry export to Application Insights.

Enabled only when APPLICATIONINSIGHTS_CONNECTION_STRING is set, so local runs
and tests stay offline. Each replica reports the Container Apps revision it
belongs to (as ``service.version``) and its replica name (as
``service.instance.id``, which App Insights shows as ``cloud_RoleInstance``).
The canary analysis in the deploy workflow filters requests by revision.
"""

from __future__ import annotations

import logging
import os
from typing import Any

log = logging.getLogger("dfcast.telemetry")


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
    log.info("telemetry enabled", extra={"fields": resource_attributes()})
    return True


def instrument_app(app: Any) -> None:
    """Trace incoming requests. Probe endpoints are excluded to save ingestion."""
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz,readyz")
