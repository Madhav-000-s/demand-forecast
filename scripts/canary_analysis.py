"""Canary analysis: drive traffic, then judge the canary revision from App Insights.

Container Apps splits traffic by weight but has no automated canary analysis,
so deploy.yml runs this while the new revision holds 10% of traffic:

    python scripts/canary_analysis.py --app-url https://<fqdn> --revision <canary revision> \
        --appinsights-app-id <App Insights application id> --minutes 10

Every minute it sends synthetic forecast requests to the public URL (so the
traffic split applies) and queries App Insights for the canary revision's
request count, 5xx rate and p95 latency. It fails fast if a threshold is
breached once enough requests have been seen, and fails at the end if the
canary never received enough traffic to judge.

Exit code 0 = promote, 1 = roll back. Needs an Azure CLI login.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import random
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Stats:
    requests: int
    errors: int
    p95_ms: float

    @property
    def error_rate(self) -> float:
        return self.errors / self.requests if self.requests else 0.0


QUERY = """
requests
| where timestamp > ago({lookback}m)
| where application_Version == '{revision}'
| where name has '/v1/'
| summarize n = count(), errors = countif(toint(resultCode) >= 500), p95 = percentile(duration, 95)
"""


def query_stats(app_id: str, revision: str, lookback_min: int) -> Stats:
    """Query the App Insights REST API through `az rest` (core CLI, no extension)."""
    body = json.dumps({"query": QUERY.format(lookback=lookback_min, revision=revision)})
    out = subprocess.run(
        [
            "az", "rest", "--method", "post",
            "--url", f"https://api.applicationinsights.io/v1/apps/{app_id}/query",
            "--resource", "https://api.applicationinsights.io",
            "--headers", "Content-Type=application/json",
            "--body", body,
            "-o", "json",
        ],
        check=True, capture_output=True, text=True,
    ).stdout  # fmt: skip
    rows = json.loads(out)["tables"][0]["rows"]
    if not rows or rows[0][0] in (None, 0):
        return Stats(0, 0, 0.0)
    n, errors, p95 = rows[0]
    return Stats(int(n), int(errors or 0), float(p95 or 0.0))


def traffic(app_url: str, stop: threading.Event, rps: float) -> None:
    """Send forecast requests to the public URL until stopped."""
    rng = random.Random()
    while not stop.is_set():
        body = {
            "store": rng.randint(1, 10),
            "item": rng.randint(1, 50),
            "start_date": "2018-01-01",
            "horizon_days": rng.choice([7, 14, 30, 90]),
        }
        req = urllib.request.Request(
            app_url.rstrip("/") + "/v1/forecast",
            data=json.dumps(body).encode(),
            headers={"content-type": "application/json"},
            method="POST",
        )
        # errors are measured server-side from App Insights, not here
        with contextlib.suppress(urllib.error.URLError, TimeoutError, ConnectionError):
            urllib.request.urlopen(req, timeout=15).read()
        stop.wait(1.0 / rps)


def summary(line: str) -> None:
    print(line, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--app-url", required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--appinsights-app-id", required=True, help="App Insights application (app) id")
    p.add_argument("--minutes", type=int, default=10)
    p.add_argument("--rps", type=float, default=2.0, help="synthetic requests per second per worker")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--max-error-rate", type=float, default=0.02)
    p.add_argument("--max-p95-ms", type=float, default=300.0)
    p.add_argument("--min-requests", type=int, default=30)
    p.add_argument("--ingestion-wait", type=int, default=150, help="seconds to wait for telemetry at the end")
    a = p.parse_args()

    stop = threading.Event()
    workers = [
        threading.Thread(target=traffic, args=(a.app_url, stop, a.rps), daemon=True) for _ in range(a.workers)
    ]
    for w in workers:
        w.start()

    summary(f"### Canary analysis: `{a.revision}`\n")
    summary("| minute | requests | 5xx rate | p95 ms |\n|---|---|---|---|")
    lookback = a.minutes + 5
    verdict: str | None = None
    try:
        for minute in range(1, a.minutes + 1):
            time.sleep(60)
            s = query_stats(a.appinsights_app_id, a.revision, lookback)
            summary(f"| {minute} | {s.requests} | {s.error_rate:.2%} | {s.p95_ms:.0f} |")
            if s.requests >= a.min_requests and s.error_rate > a.max_error_rate:
                verdict = f"5xx rate {s.error_rate:.2%} above {a.max_error_rate:.0%}"
                break
            if s.requests >= a.min_requests and s.p95_ms > a.max_p95_ms:
                verdict = f"p95 {s.p95_ms:.0f} ms above {a.max_p95_ms:.0f} ms"
                break
    finally:
        stop.set()

    if verdict is None:
        time.sleep(a.ingestion_wait)  # let the last minutes of telemetry arrive
        s = query_stats(a.appinsights_app_id, a.revision, lookback + a.ingestion_wait // 60 + 1)
        summary(f"| final | {s.requests} | {s.error_rate:.2%} | {s.p95_ms:.0f} |")
        if s.requests < a.min_requests:
            verdict = f"only {s.requests} canary requests recorded (< {a.min_requests}); cannot judge"
        elif s.error_rate > a.max_error_rate:
            verdict = f"5xx rate {s.error_rate:.2%} above {a.max_error_rate:.0%}"
        elif s.p95_ms > a.max_p95_ms:
            verdict = f"p95 {s.p95_ms:.0f} ms above {a.max_p95_ms:.0f} ms"

    if verdict:
        summary(f"\n**Roll back:** {verdict}")
        return 1
    summary("\n**Promote:** canary within SLO thresholds")
    return 0


if __name__ == "__main__":
    sys.exit(main())
