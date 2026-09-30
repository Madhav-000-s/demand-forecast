from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import faults
from app.main import app


def test_no_fault_file_means_no_faults(tmp_path: Path) -> None:
    assert faults.load(tmp_path) == faults.Faults()
    assert not faults.load(tmp_path).active


def test_latency_fault_is_clamped(tmp_path: Path) -> None:
    (tmp_path / "fault.json").write_text(json.dumps({"extra_latency_ms": 400}))
    assert faults.load(tmp_path).extra_latency_ms == 400
    (tmp_path / "fault.json").write_text(json.dumps({"extra_latency_ms": 10**9}))
    assert faults.load(tmp_path).extra_latency_ms == faults.MAX_LATENCY_MS
    (tmp_path / "fault.json").write_text(json.dumps({"extra_latency_ms": -5}))
    assert not faults.load(tmp_path).active


@pytest.mark.parametrize("content", ["not json", "[1, 2]", '{"extra_latency_ms": "slow"}'])
def test_malformed_fault_file_is_ignored(tmp_path: Path, content: str) -> None:
    (tmp_path / "fault.json").write_text(content)
    assert faults.load(tmp_path) == faults.Faults()


def test_drill_image_adds_latency_to_v1_only(
    artifacts: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    drill = tmp_path / "drill-artifacts"
    drill.mkdir()
    for f in artifacts.iterdir():
        (drill / f.name).write_bytes(f.read_bytes())
    (drill / "fault.json").write_text(json.dumps({"extra_latency_ms": 150}))
    monkeypatch.setenv("ARTIFACT_DIR", str(drill))
    body = {"store": 1, "item": 1, "start_date": "2018-01-01", "horizon_days": 3}
    with TestClient(app) as c:
        t0 = time.perf_counter()
        assert c.get("/healthz").status_code == 200
        fast = time.perf_counter() - t0
        t0 = time.perf_counter()
        assert c.post("/v1/forecast", json=body).status_code == 200
        slow = time.perf_counter() - t0
    assert slow >= 0.15 > fast
