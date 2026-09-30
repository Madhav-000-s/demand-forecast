"""Chaos drill toolkit, driven by .github/workflows/drill.yml.

    # break a copy of the model artifacts before a drill image is built
    python scripts/drill.py prepare bad-model --artifacts artifacts --scale 1.3
    python scripts/drill.py prepare slow-release --artifacts artifacts --latency-ms 400

    # send tagged traffic (X-Traffic-Source: drill) and report client-side stats
    python scripts/drill.py traffic --app-url https://<fqdn> --profile skewed --requests 800
    python scripts/drill.py traffic --app-url https://<fqdn> --profile normal --duration 300

    # k6 summary -> the same client stats shape
    python scripts/drill.py k6-stats scripts/k6/k6-summary.json --out load.json

    # record the drill: server-side stats from App Insights + a `drill` event
    python scripts/drill.py record --name restart --start <iso> --end <iso> \\
        --appinsights-app-id <id> --client-stats traffic.json --expected "..." --outcome "..."

Profiles: ``normal`` spreads requests over every series and the whole
servable window (what the drift reference expects); ``skewed`` sends only
stores 1-2 and items 1-5, which the drift job should flag.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
import threading
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))

import appinsights  # scripts/ sibling module

WINDOW_START = date(2018, 1, 1)
WINDOW_DAYS = 91
ROLE = "dfcast-drill"


# --- prepare ------------------------------------------------------------------


def prepare_bad_model(artifacts: Path, scale: float) -> str:
    """Scale the shipped sales history: the model still loads, answers 200 and
    returns plausible numbers, but every forecast is off by roughly ``scale``.
    Only the smoke test's comparison with training output can tell."""
    path = artifacts / "history.npz"
    with np.load(path) as h:
        data = {k: h[k] for k in h.files}
    data["values"] = (data["values"].astype(np.float64) * scale).astype(data["values"].dtype)
    np.savez_compressed(path, **data)
    return f"history.npz scaled by {scale}: forecasts about {100 * (scale - 1):+.0f}%, HTTP 200s throughout"


def prepare_slow_release(artifacts: Path, latency_ms: int) -> str:
    """Add artifacts/fault.json; the API then delays every /v1 request."""
    (artifacts / "fault.json").write_text(json.dumps({"extra_latency_ms": latency_ms}))
    return f"fault.json: +{latency_ms} ms on every /v1 request (SLO is p95 < 300 ms)"


# --- traffic ------------------------------------------------------------------


def request_body(rng: random.Random, profile: str) -> dict[str, Any]:
    horizon = rng.choice([7, 14, 30, 90])
    start = WINDOW_START + timedelta(days=rng.randint(0, WINDOW_DAYS - horizon))
    if profile == "skewed":
        store, item = rng.choice([1, 2]), rng.randint(1, 5)
    else:
        store, item = rng.randint(1, 10), rng.randint(1, 50)
    return {"store": store, "item": item, "start_date": start.isoformat(), "horizon_days": horizon}


@dataclass
class ClientStats:
    profile: str
    source: str
    started: str = ""
    finished: str = ""
    sent: int = 0
    ok: int = 0
    client_errors: int = 0  # 4xx
    server_errors: int = 0  # 5xx
    failed: int = 0  # timeouts, resets, refused
    latencies_ms: list[float] = field(default_factory=list, repr=False)

    def summary(self) -> dict[str, Any]:
        lat = np.array(self.latencies_ms) if self.latencies_ms else np.zeros(1)
        d = asdict(self)
        d.pop("latencies_ms")
        d.update(
            client_p50_ms=round(float(np.percentile(lat, 50)), 1),
            client_p95_ms=round(float(np.percentile(lat, 95)), 1),
            client_max_ms=round(float(lat.max()), 1),
        )
        return d


def send_one(
    app_url: str, body: dict[str, Any], source: str, stats: ClientStats, lock: threading.Lock
) -> None:
    req = urllib.request.Request(
        app_url.rstrip("/") + "/v1/forecast",
        data=json.dumps(body).encode(),
        headers={"content-type": "application/json", "x-traffic-source": source},
        method="POST",
    )
    t0 = time.perf_counter()
    status = 0
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        status = e.code
    except (urllib.error.URLError, TimeoutError, ConnectionError):
        status = 0
    elapsed = (time.perf_counter() - t0) * 1000
    with lock:
        stats.sent += 1
        if status == 0:
            stats.failed += 1
        elif status >= 500:
            stats.server_errors += 1
        elif status >= 400:
            stats.client_errors += 1
        else:
            stats.ok += 1
            stats.latencies_ms.append(elapsed)


def run_traffic(
    app_url: str,
    profile: str,
    source: str,
    requests: int | None,
    duration_s: float | None,
    workers: int,
    rps: float | None = None,
    seed: int | None = None,
) -> ClientStats:
    stats = ClientStats(profile=profile, source=source, started=_now())
    lock = threading.Lock()
    budget = [requests if requests is not None else 10**9]
    deadline = time.monotonic() + duration_s if duration_s else float("inf")

    def worker(i: int) -> None:
        rng = random.Random(None if seed is None else seed + i)
        while time.monotonic() < deadline:
            with lock:
                if budget[0] <= 0:
                    return
                budget[0] -= 1
            send_one(app_url, request_body(rng, profile), source, stats, lock)
            if rps:
                time.sleep(workers / rps)

    threads = [threading.Thread(target=worker, args=(i,), daemon=True) for i in range(workers)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stats.finished = _now()
    return stats


def k6_client_stats(summary: dict[str, Any]) -> dict[str, Any]:
    """Client-side numbers from a k6 handleSummary() JSON, in ClientStats terms."""
    m = summary["metrics"]
    dur = m["http_req_duration"]["values"]
    sent = int(m["http_reqs"]["values"]["count"])
    failed_rate = float(m["http_req_failed"]["values"]["rate"])
    return {
        "profile": "k6",
        "source": "load",
        "sent": sent,
        "failed": round(sent * failed_rate),
        "rps": round(float(m["http_reqs"]["values"]["rate"]), 1),
        "max_vus": int(m.get("vus_max", {}).get("values", {}).get("max", 0)),
        "client_p50_ms": round(float(dur["med"]), 1),
        "client_p95_ms": round(float(dur["p(95)"]), 1),
        "client_max_ms": round(float(dur["max"]), 1),
    }


# --- record -------------------------------------------------------------------


def record(
    name: str,
    start: datetime,
    end: datetime,
    app_id: str | None,
    client: dict[str, Any] | None,
    expected: str,
    outcome: str,
    passed: bool,
    extra: dict[str, str] | None = None,
    sources: list[str] | None = None,
) -> dict[str, Any]:
    server: dict[str, Any] = {}
    if app_id:
        server = appinsights.window_stats(app_id, start, end, sources=sources or ["drill"])
        server_all = appinsights.window_stats(app_id, start, end)
        server["all_sources_requests"] = server_all["requests"]
        server["all_sources_errors"] = server_all["errors"]
        server["replicas_all"] = server_all["replicas"]
    result = {
        "drill": name,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "expected": expected,
        "outcome": outcome,
        "passed": passed,
        "client": client or {},
        "server": server,
        **(extra or {}),
    }
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if conn:
        props = {"drill": name, "expected": expected, "outcome": outcome, "passed": str(passed).lower()}
        props.update(extra or {})
        props["run_url"] = _run_url()
        meas = {f"client_{k}": float(v) for k, v in (client or {}).items() if isinstance(v, (int, float))}
        meas.update({f"server_{k}": float(v) for k, v in server.items() if isinstance(v, (int, float))})
        meas["duration_s"] = (end - start).total_seconds()
        appinsights.send_event(conn, "drill", props, meas, ROLE)
    _summary(markdown(result))
    return result


def markdown(result: dict[str, Any]) -> str:
    verdict = "PASSED" if result["passed"] else "FAILED"
    lines = [
        f"### Drill `{result['drill']}`: {verdict}\n",
        f"- Window: {result['start']} to {result['end']}",
        f"- Expected: {result['expected']}",
        f"- Outcome: {result['outcome']}\n",
    ]
    rows = [("client", k, v) for k, v in result["client"].items() if k not in ("profile", "source")]
    rows += [("server", k, v) for k, v in result["server"].items()]
    if rows:
        lines += ["| side | metric | value |", "|---|---|---|"]
        lines += [f"| {side} | {k} | {v} |" for side, k, v in rows]
    return "\n".join(lines)


def report(app_id: str, start: datetime, end: datetime) -> str:
    """Markdown: per-minute timeline and replica starts for a window."""
    lines = [f"### Telemetry {start.isoformat()} to {end.isoformat()}\n"]
    rows = appinsights.timeline(app_id, start, end)
    lines += ["| minute (UTC) | requests | 5xx | p50 ms | p95 ms | replicas |", "|---|---|---|---|---|---|"]
    for r in rows:
        cells = [str(r["minute"])[11:16], r["requests"], r["errors"], r["p50"], r["p95"], r["replicas"]]
        lines.append("| " + " | ".join(str(c) for c in cells) + " |")
    starts = appinsights.replica_starts(app_id, start, end)
    lines += ["", "| replica start (UTC) | replica | model load s |", "|---|---|---|"]
    lines += [f"| {str(r['timestamp'])[11:19]} | {r['replica']} | {r['load_seconds']} |" for r in starts]
    return "\n".join(lines)


# --- helpers ------------------------------------------------------------------


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _run_url() -> str:
    if not os.environ.get("GITHUB_RUN_ID"):
        return ""
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"


def _summary(text: str) -> None:
    print(text, flush=True)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(text + "\n")


def _parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("prepare", help="break a copy of the artifacts for a drill image")
    pr.add_argument("kind", choices=["bad-model", "slow-release"])
    pr.add_argument("--artifacts", type=Path, default=Path("artifacts"))
    pr.add_argument("--scale", type=float, default=1.3)
    pr.add_argument("--latency-ms", type=int, default=400)

    tr = sub.add_parser("traffic", help="send tagged forecast requests")
    tr.add_argument("--app-url", required=True)
    tr.add_argument("--profile", choices=["normal", "skewed"], default="normal")
    tr.add_argument("--source", default="drill")
    tr.add_argument("--requests", type=int)
    tr.add_argument("--duration", type=float, help="seconds")
    tr.add_argument("--workers", type=int, default=8)
    tr.add_argument("--rps", type=float, help="total requests per second cap")
    tr.add_argument("--out", type=Path)

    rp = sub.add_parser("report", help="per-minute telemetry timeline for a window")
    rp.add_argument("--start", required=True, type=_parse_time)
    rp.add_argument("--end", required=True, type=_parse_time)
    rp.add_argument("--appinsights-app-id", required=True)

    k6 = sub.add_parser("k6-stats", help="convert a k6 summary into client stats JSON")
    k6.add_argument("summary", type=Path)
    k6.add_argument("--out", type=Path, required=True)

    rc = sub.add_parser("record", help="write the drill result (App Insights event + summary)")
    rc.add_argument("--name", required=True)
    rc.add_argument("--start", required=True, type=_parse_time)
    rc.add_argument("--end", type=_parse_time)
    rc.add_argument("--appinsights-app-id")
    rc.add_argument("--client-stats", type=Path)
    rc.add_argument("--expected", required=True)
    rc.add_argument("--outcome", required=True)
    rc.add_argument("--passed", choices=["true", "false"], required=True)
    rc.add_argument("--extra", action="append", default=[], help="key=value property, repeatable")
    rc.add_argument("--sources", default="drill", help="comma-separated X-Traffic-Source values")
    rc.add_argument("--out", type=Path)

    a = p.parse_args(argv)
    if a.cmd == "prepare":
        if a.kind == "bad-model":
            print(prepare_bad_model(a.artifacts, a.scale))
        else:
            print(prepare_slow_release(a.artifacts, a.latency_ms))
        return 0

    if a.cmd == "traffic":
        if a.requests is None and a.duration is None:
            p.error("give --requests or --duration")
        stats = run_traffic(a.app_url, a.profile, a.source, a.requests, a.duration, a.workers, a.rps)
        summary = stats.summary()
        print(json.dumps(summary, indent=2))
        if a.out:
            a.out.write_text(json.dumps(summary, indent=2))
        return 0

    if a.cmd == "report":
        _summary(report(a.appinsights_app_id, a.start, a.end))
        return 0

    if a.cmd == "k6-stats":
        k6_stats = k6_client_stats(json.loads(a.summary.read_text()))
        a.out.write_text(json.dumps(k6_stats, indent=2))
        print(json.dumps(k6_stats, indent=2))
        return 0

    client = json.loads(a.client_stats.read_text()) if a.client_stats else None
    extra = dict(kv.split("=", 1) for kv in a.extra)
    end = a.end or datetime.now(timezone.utc)
    result = record(
        a.name,
        a.start,
        end,
        a.appinsights_app_id,
        client,
        a.expected,
        a.outcome,
        a.passed == "true",
        extra,
        sources=[s for s in a.sources.split(",") if s],
    )
    if a.out:
        a.out.write_text(json.dumps(result, indent=2, default=str))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
