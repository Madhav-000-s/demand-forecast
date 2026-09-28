"""Decision logic of scripts/canary_analysis.py with App Insights and time stubbed."""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def ca(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("canary_analysis", ROOT / "scripts/canary_analysis.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "canary_analysis", mod)  # dataclasses need it registered
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod.time, "sleep", lambda _s: None)
    monkeypatch.setattr(mod, "traffic", lambda *_a: None)  # no network
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    yield mod


def run(ca: ModuleType, monkeypatch: pytest.MonkeyPatch, stats: list, minutes: int = 3) -> int:
    calls = iter(stats)
    monkeypatch.setattr(ca, "query_stats", lambda *_a: next(calls))
    argv = ["x", "--app-url", "https://app", "--revision", "rev-2", "--appinsights-app-id", "id"]
    monkeypatch.setattr(sys, "argv", [*argv, "--minutes", str(minutes)])
    return ca.main()


def test_healthy_canary_is_promoted(ca: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = ca.Stats(100, 0, 120.0)
    assert run(ca, monkeypatch, [ok, ok, ok, ok]) == 0


def test_error_spike_rolls_back_early(ca: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run(ca, monkeypatch, [ca.Stats(50, 5, 100.0)]) == 1  # 10% 5xx at minute 1


def test_slow_canary_rolls_back(ca: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    ok = ca.Stats(40, 0, 100.0)
    assert run(ca, monkeypatch, [ok, ca.Stats(80, 0, 900.0)]) == 1


def test_too_little_traffic_cannot_be_judged(ca: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    few = ca.Stats(3, 0, 50.0)
    assert run(ca, monkeypatch, [few, few, few, few]) == 1


def test_a_few_early_errors_below_min_requests_do_not_fail_fast(
    ca: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    stats = [ca.Stats(5, 2, 100.0), ca.Stats(200, 2, 110.0), ca.Stats(300, 2, 110.0), ca.Stats(320, 2, 110.0)]
    assert run(ca, monkeypatch, stats) == 0
