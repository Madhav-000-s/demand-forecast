"""scripts/drill.py and scripts/appinsights.py, with no network beyond localhost."""

from __future__ import annotations

import importlib.util
import json
import random
import shutil
import sys
import threading
from collections.abc import Iterator
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from app import faults
from app.model import ForecastModel
from ml import canary

ROOT = Path(__file__).resolve().parents[2]


def load_script(name: str, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def drill(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    for var in ("GITHUB_STEP_SUMMARY", "APPLICATIONINSIGHTS_CONNECTION_STRING", "GITHUB_RUN_ID"):
        monkeypatch.delenv(var, raising=False)
    yield load_script("drill", monkeypatch)


@pytest.fixture
def ai(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    return load_script("appinsights", monkeypatch)


# --- prepare ------------------------------------------------------------------


def test_bad_model_serves_wrong_numbers_that_the_smoke_test_catches(
    drill: ModuleType, artifacts: Path, tmp_path: Path
) -> None:
    broken = tmp_path / "artifacts"
    shutil.copytree(artifacts, broken)
    note = drill.prepare_bad_model(broken, 1.3)
    assert "+30%" in note

    reference = json.loads((artifacts / "canary_reference.json").read_text())
    good, bad = ForecastModel.load(artifacts), ForecastModel.load(broken)
    served = []
    for case in reference["cases"]:
        r = case["request"]
        start = date.fromisoformat(r["start_date"])
        units, _ = bad.forecast(r["store"], r["item"], start, r["horizon_days"])
        served.append(units)
        assert units != good.forecast(r["store"], r["item"], start, r["horizon_days"])[0]
    failures = canary.check(reference, served)
    assert failures and "differs from training output" in failures[0]


def test_slow_release_writes_a_fault_the_api_reads(drill: ModuleType, tmp_path: Path) -> None:
    drill.prepare_slow_release(tmp_path, 400)
    assert faults.load(tmp_path).extra_latency_ms == 400


# --- traffic ------------------------------------------------------------------


@pytest.mark.parametrize("profile", ["normal", "skewed"])
def test_requests_stay_in_the_servable_window(drill: ModuleType, profile: str) -> None:
    rng = random.Random(0)
    bodies = [drill.request_body(rng, profile) for _ in range(400)]
    for b in bodies:
        start = date.fromisoformat(b["start_date"])
        assert date(2018, 1, 1) <= start
        assert start + timedelta(days=b["horizon_days"] - 1) <= date(2018, 4, 1)
    stores = {b["store"] for b in bodies}
    items = {b["item"] for b in bodies}
    if profile == "skewed":
        assert stores <= {1, 2} and items <= set(range(1, 6))
    else:
        assert len(stores) == 10 and len(items) > 40


@pytest.fixture
def fake_api() -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Answers 200, except store 9 -> 500 and store 8 -> 422; records headers."""
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append({"source": self.headers.get("x-traffic-source"), **body})
            code = 500 if body["store"] == 9 else 422 if body["store"] == 8 else 200
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"{}")

        def log_message(self, *_a: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{server.server_address[1]}", seen
    server.shutdown()


def test_traffic_counts_outcomes_and_tags_requests(
    drill: ModuleType, fake_api: tuple[str, list[dict[str, Any]]]
) -> None:
    url, seen = fake_api
    stats = drill.run_traffic(url, "normal", "drill", requests=200, duration_s=None, workers=4, seed=1)
    summary = stats.summary()
    assert summary["sent"] == 200 == len(seen)
    assert summary["server_errors"] == sum(r["store"] == 9 for r in seen)
    assert summary["client_errors"] == sum(r["store"] == 8 for r in seen)
    assert summary["ok"] + summary["server_errors"] + summary["client_errors"] == 200
    assert {r["source"] for r in seen} == {"drill"}
    assert summary["client_p95_ms"] >= summary["client_p50_ms"] > 0


def test_unreachable_app_counts_as_failed(drill: ModuleType) -> None:
    stats = drill.run_traffic("http://127.0.0.1:9", "normal", "drill", 5, None, 1)
    assert stats.failed == 5 and stats.ok == 0


# --- record -------------------------------------------------------------------


def test_record_without_azure(drill: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    summary = tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    result = drill.record(
        "restart", start, start + timedelta(minutes=5), None, {"sent": 10, "failed": 0},
        "no user-visible errors", "0 errors", True, {"revision": "r1"},
    )  # fmt: skip
    assert result["passed"] and result["revision"] == "r1"
    text = summary.read_text()
    assert "Drill `restart`: PASSED" in text and "| client | sent | 10 |" in text


def test_record_sends_event_with_measurements(drill: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[tuple[str, dict, dict]] = []
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=k")
    monkeypatch.setattr(drill.appinsights, "send_event", lambda _c, n, p, m, _r: sent.append((n, p, m)))
    monkeypatch.setattr(
        drill.appinsights,
        "window_stats",
        lambda *_a, **_k: {"requests": 50, "errors": 1, "p95": 420.0, "replicas": 2, "revisions": ["a"]},
    )
    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    drill.record("slow-release", start, start + timedelta(minutes=1), "app", None, "e", "o", False)
    name, props, meas = sent[0]
    assert name == "drill" and props["passed"] == "false"
    assert meas["server_p95"] == 420.0 and meas["duration_s"] == 60.0
    assert "server_revisions" not in meas  # lists are not measurements


def test_cli_record_exit_code_follows_the_verdict(drill: ModuleType) -> None:
    base = ["record", "--name", "x", "--start", "2026-10-01T10:00:00Z", "--expected", "e", "--outcome", "o"]
    assert drill.main([*base, "--passed", "true"]) == 0
    assert drill.main([*base, "--passed", "false"]) == 1


# --- appinsights --------------------------------------------------------------


def test_window_stats_query_and_parsing(ai: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def fake(_app: str, kql: str) -> list[list[Any]]:
        seen.append(kql)
        return [[120, 3, 11.2, 240.55, 410.0, 900.0, 2, '["rev-a","rev-b"]']]

    monkeypatch.setattr(ai, "query", fake)
    start = datetime(2026, 10, 1, 10, 0, tzinfo=timezone.utc)
    stats = ai.window_stats("app", start, start + timedelta(minutes=5), sources=["drill", "bad' or 1==1"])
    assert stats == {
        "requests": 120, "errors": 3, "p50": 11.2, "p95": 240.6, "p99": 410.0,
        "max_ms": 900.0, "replicas": 2, "revisions": ["rev-a", "rev-b"],
    }  # fmt: skip
    assert "datetime(2026-10-01T10:00:00Z) .. datetime(2026-10-01T10:05:00Z)" in seen[0]
    assert "in ('drill')" in seen[0] and "bad'" not in seen[0]


def test_event_envelope_stringifies_properties(ai: ModuleType) -> None:
    env = ai.event_envelope("drill", {"passed": True, "n": 3}, {"x": 1}, "ikey", "role")  # type: ignore[dict-item]
    base = env["data"]["baseData"]
    assert base["properties"] == {"passed": "True", "n": "3"} and base["measurements"] == {"x": 1.0}
    assert env["iKey"] == "ikey" and env["tags"]["ai.cloud.role"] == "role"


def test_k6_summary_conversion(drill: ModuleType, tmp_path: Path) -> None:
    summary = {
        "metrics": {
            "http_reqs": {"values": {"count": 2000, "rate": 6.67}},
            "http_req_failed": {"values": {"rate": 0.005}},
            "http_req_duration": {"values": {"med": 255.1, "p(95)": 301.26, "max": 2100.0}},
            "vus_max": {"values": {"max": 100}},
        }
    }
    (tmp_path / "s.json").write_text(json.dumps(summary))
    assert drill.main(["k6-stats", str(tmp_path / "s.json"), "--out", str(tmp_path / "o.json")]) == 0
    stats = json.loads((tmp_path / "o.json").read_text())
    assert stats["sent"] == 2000 and stats["failed"] == 10 and stats["client_p95_ms"] == 301.3
    assert stats["max_vus"] == 100 and stats["rps"] == 6.7


def test_report_renders_timeline_and_replica_starts(
    drill: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        drill.appinsights,
        "timeline",
        lambda *_a: [
            {
                "minute": "2026-09-30T17:11:00Z",
                "requests": 900,
                "errors": 0,
                "p50": 480.2,
                "p95": 1348.0,
                "replicas": 1,
            }
        ],
    )
    monkeypatch.setattr(
        drill.appinsights,
        "replica_starts",
        lambda *_a: [
            {"timestamp": "2026-09-30T17:10:58Z", "replica": "r-1", "revision": "rev", "load_seconds": 3.2}
        ],
    )
    start = datetime(2026, 9, 30, 17, 9, tzinfo=timezone.utc)
    text = drill.report("app", start, start + timedelta(minutes=10))
    assert "| 17:11 | 900 | 0 | 480.2 | 1348.0 | 1 |" in text
    assert "| 17:10:58 | r-1 | 3.2 |" in text


def test_timeline_parsing(ai: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai, "query", lambda *_a: [["2026-09-30T17:11:00Z", 900, 2, 480.24, 1348.04, 2]])
    start = datetime(2026, 9, 30, 17, 9, tzinfo=timezone.utc)
    rows = ai.timeline("app", start, start + timedelta(minutes=10))
    assert rows == [
        {
            "minute": "2026-09-30T17:11:00Z",
            "requests": 900,
            "errors": 2,
            "p50": 480.2,
            "p95": 1348.0,
            "replicas": 2,
        }
    ]


def test_record_uses_the_requested_sources(drill: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[Any] = []

    def fake(_app: str, _s: datetime, _e: datetime, sources: list[str] | None = None) -> dict:
        seen.append(sources)
        return {"requests": 1, "errors": 0, "replicas": 1}

    monkeypatch.setattr(drill.appinsights, "window_stats", fake)
    start = datetime(2026, 9, 30, 17, 9, tzinfo=timezone.utc)
    drill.record("load", start, start, "app", None, "e", "o", True, sources=["load"])
    assert seen == [["load"], None]


def test_drill_traffic_sends_the_ops_token(
    drill: ModuleType, fake_api: tuple[str, list[dict[str, Any]]], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("OPS_BYPASS_TOKEN", "tok")
    assert drill.ops_headers({"a": "b"}) == {"a": "b", "x-ops-token": "tok"}
    monkeypatch.delenv("OPS_BYPASS_TOKEN")
    assert drill.ops_headers({"a": "b"}) == {"a": "b"}
