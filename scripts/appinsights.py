"""Small Application Insights helpers shared by the ops scripts.

- ``query``: run KQL through the App Insights REST API with ``az rest`` (core
  Azure CLI, no extension; needs an ``az login``).
- ``send_event``: write a custom event through the ingestion endpoint of a
  connection string (drift checks and drill records land in ``customEvents``).
- ``window_stats``: server-side request statistics for a time window, the
  numbers postmortems quote.
"""

from __future__ import annotations

import json
import subprocess
import urllib.request
from datetime import datetime, timezone
from typing import Any


def query(app_id: str, kql: str) -> list[list[Any]]:
    out = subprocess.run(
        [
            "az", "rest", "--method", "post",
            "--url", f"https://api.applicationinsights.io/v1/apps/{app_id}/query",
            "--resource", "https://api.applicationinsights.io",
            "--headers", "Content-Type=application/json",
            "--body", json.dumps({"query": kql}),
            "-o", "json",
        ],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    rows: list[list[Any]] = json.loads(out)["tables"][0]["rows"]
    return rows


def parse_connection_string(conn: str) -> tuple[str, str]:
    """(instrumentation key, track URL) from an App Insights connection string."""
    parts = dict(p.split("=", 1) for p in conn.split(";") if "=" in p)
    ikey = parts.get("InstrumentationKey", "")
    endpoint = parts.get("IngestionEndpoint", "https://dc.services.visualstudio.com/")
    if not ikey:
        raise ValueError("connection string has no InstrumentationKey")
    return ikey, endpoint.rstrip("/") + "/v2.1/track"


def event_envelope(
    name: str,
    properties: dict[str, str],
    measurements: dict[str, float],
    ikey: str,
    role: str,
    time: datetime | None = None,
) -> dict[str, Any]:
    return {
        "name": "Microsoft.ApplicationInsights.Event",
        "time": (time or datetime.now(timezone.utc)).isoformat(),
        "iKey": ikey,
        "tags": {"ai.cloud.role": role},
        "data": {
            "baseType": "EventData",
            "baseData": {
                "ver": 2,
                "name": name,
                "properties": {k: str(v) for k, v in properties.items()},
                "measurements": {k: float(v) for k, v in measurements.items()},
            },
        },
    }


def send_event(
    connection_string: str,
    name: str,
    properties: dict[str, str],
    measurements: dict[str, float],
    role: str = "dfcast-ops",
) -> None:
    ikey, url = parse_connection_string(connection_string)
    body = json.dumps([event_envelope(name, properties, measurements, ikey, role)]).encode()
    req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=30) as r:
        result = json.loads(r.read() or b"{}")
    if result.get("itemsAccepted", 0) < 1:
        raise RuntimeError(f"App Insights rejected the event: {result}")


WINDOW_STATS = """
requests
| where timestamp between (datetime({start}) .. datetime({end}))
| where name has '/v1/'
{source_filter}
| summarize requests = count(),
            errors = countif(toint(resultCode) >= 500),
            p50 = percentile(duration, 50), p95 = percentile(duration, 95),
            p99 = percentile(duration, 99), max_ms = max(duration),
            replicas = dcount(cloud_RoleInstance),
            revisions = make_set(application_Version, 10)
"""


def window_stats(app_id: str, start: datetime, end: datetime, sources: list[str] | None = None) -> dict:
    """Server-side /v1 request stats between two UTC times.

    ``sources`` limits to X-Traffic-Source values via the request log lines
    (requests and traces share operation_Id).
    """
    source_filter = ""
    if sources:
        wanted = ", ".join(f"'{s}'" for s in sources if s.replace("-", "").isalnum())
        source_filter = (
            "| join kind=inner (traces | where message == 'request'"
            f" | where tostring(customDimensions.traffic_source) in ({wanted})"
            " | project operation_Id) on operation_Id"
        )
    kql = WINDOW_STATS.format(start=_iso(start), end=_iso(end), source_filter=source_filter)
    rows = query(app_id, kql)
    keys = ["requests", "errors", "p50", "p95", "p99", "max_ms", "replicas", "revisions"]
    if not rows:
        return dict.fromkeys(keys, 0)
    stats = dict(zip(keys, rows[0], strict=False))
    for k in ("p50", "p95", "p99", "max_ms"):
        stats[k] = round(float(stats[k] or 0.0), 1)
    stats["revisions"] = (
        json.loads(stats["revisions"]) if isinstance(stats["revisions"], str) else stats["revisions"]
    )
    return stats


def _iso(t: datetime) -> str:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
