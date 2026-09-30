"""scripts/drift_check.py with App Insights stubbed."""

from __future__ import annotations

import importlib.util
import json
import sys
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np
import pytest

from ml.drift_stats import reference_stats
from ml.features import CATEGORICAL_FEATURES, FEATURE_NAMES, HISTORY_FEATURES

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def dc(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    spec = importlib.util.spec_from_file_location("drift_check", ROOT / "scripts/drift_check.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "drift_check", mod)
    spec.loader.exec_module(mod)
    for var in (
        "GITHUB_STEP_SUMMARY",
        "GITHUB_OUTPUT",
        "GITHUB_RUN_ID",
        "APPLICATIONINSIGHTS_CONNECTION_STRING",
    ):
        monkeypatch.delenv(var, raising=False)
    yield mod


def sample(rng: np.random.Generator, n: int, stores: tuple[int, ...] = tuple(range(1, 11))) -> np.ndarray:
    """Feature rows: uniform store/item, history features ~ N(50, 10)."""
    x = np.zeros((n, len(FEATURE_NAMES)))
    x[:, FEATURE_NAMES.index("store")] = rng.choice(stores, n)
    x[:, FEATURE_NAMES.index("item")] = rng.integers(1, 51, n)
    for name in HISTORY_FEATURES:
        x[:, FEATURE_NAMES.index(name)] = rng.normal(50, 10, n)
    return x


@pytest.fixture(scope="module")
def reference() -> dict[str, Any]:
    return reference_stats(sample(np.random.default_rng(0), 45_500), FEATURE_NAMES, CATEGORICAL_FEATURES)


def rows(x: np.ndarray) -> list[dict[str, float]]:
    return [dict(zip(FEATURE_NAMES, map(float, r), strict=True)) for r in x]


def evaluate(dc: ModuleType, reference: dict, x: np.ndarray, **kw: Any) -> Any:
    args = {"model_version": "v1", "hours": 6, "threshold": 0.25, "min_samples": 500, **kw}
    return dc.evaluate(reference, rows(x), **args)


def test_normal_traffic_is_ok(dc: ModuleType, reference: dict) -> None:
    report = evaluate(dc, reference, sample(np.random.default_rng(1), 1_000))
    assert report.status == "ok"
    assert set(report.psi) == set(dc.MONITORED)
    assert report.max_psi < 0.25 and not report.drifted


def test_skewed_store_mix_is_drift(dc: ModuleType, reference: dict) -> None:
    report = evaluate(dc, reference, sample(np.random.default_rng(2), 1_000, stores=(1, 2)))
    assert report.status == "drift"
    assert report.drifted[0] == "store" == report.max_feature


def test_shifted_history_features_are_drift(dc: ModuleType, reference: dict) -> None:
    x = sample(np.random.default_rng(3), 1_000)
    x[:, FEATURE_NAMES.index("lag_91")] += 25
    report = evaluate(dc, reference, x)
    assert report.status == "drift" and "lag_91" in report.drifted


def test_small_samples_never_alert(dc: ModuleType, reference: dict) -> None:
    report = evaluate(dc, reference, sample(np.random.default_rng(4), 100, stores=(1,)))
    assert report.status == "insufficient_data"
    assert report.drifted  # PSI is still computed and shown


def test_no_traffic(dc: ModuleType) -> None:
    report = dc.evaluate({}, [], model_version="", hours=6, threshold=0.25, min_samples=500)
    assert report.status == "insufficient_data" and report.samples == 0 and report.max_psi == 0.0


def test_calendar_features_are_not_monitored(dc: ModuleType) -> None:
    assert not {"year", "month", "dayofyear"} & set(dc.MONITORED)
    assert {"store", "item", "lag_91"} <= set(dc.MONITORED)


def test_queries_exclude_synthetic_traffic_and_validate_versions(
    dc: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[str] = []

    def fake(_app: str, query: str) -> list[list[Any]]:
        seen.append(query)
        return [['{"store": 1}'], ["not json"]]

    monkeypatch.setattr(dc, "run_query", fake)
    assert dc.fetch_features("app", "20260930.0251-d94dbfa", 6) == [{"store": 1}]
    assert "source !in ('canary', 'smoke')" in seen[0]
    assert "model_version == '20260930.0251-d94dbfa'" in seen[0]
    with pytest.raises(ValueError):
        dc.fetch_features("app", "x' or 1==1 //", 6)


def test_served_version_picks_the_busiest(dc: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dc, "run_query", lambda *_a: [["v2", 900], ["v1", 40]])
    assert dc.served_version("app", 6) == "v2"
    monkeypatch.setattr(dc, "run_query", lambda *_a: [])
    assert dc.served_version("app", 6) == ""


def test_event_envelope(dc: ModuleType, reference: dict) -> None:
    report = evaluate(dc, reference, sample(np.random.default_rng(5), 600, stores=(3,)))
    ikey, url = dc.parse_connection_string(
        "InstrumentationKey=abc;IngestionEndpoint=https://centralindia-0.in.applicationinsights.azure.com/;x=y"
    )
    assert ikey == "abc"
    assert url == "https://centralindia-0.in.applicationinsights.azure.com/v2.1/track"
    env = dc.event_envelope(report, ikey, "https://github.com/run/1")
    base = env["data"]["baseData"]
    assert base["name"] == "drift_check"
    assert base["properties"]["status"] == "drift"
    assert base["measurements"]["max_psi"] == report.max_psi
    assert base["measurements"]["psi_store"] == report.psi["store"]
    assert all(isinstance(v, str) for v in base["properties"].values())
    json.dumps(env)


def test_cli_writes_report_and_outputs(
    dc: ModuleType, reference: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref_path = tmp_path / "reference_stats.json"
    ref_path.write_text(json.dumps(reference))
    x = sample(np.random.default_rng(6), 800)
    monkeypatch.setattr(dc, "run_query", lambda *_a: [[json.dumps(r)] for r in rows(x)])
    sent: list[Any] = []
    monkeypatch.setattr(dc, "send_event", lambda report, conn, url: sent.append((report.status, conn)))
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=k")
    out, summary = tmp_path / "out", tmp_path / "summary.md"
    monkeypatch.setenv("GITHUB_OUTPUT", str(out))
    monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))
    argv = ["check", "--appinsights-app-id", "app", "--model-version", "v1", "--reference", str(ref_path)]
    assert dc.main([*argv, "--report", str(tmp_path / "r.json")]) == 0
    assert sent == [("ok", "InstrumentationKey=k")]
    assert "status=ok" in out.read_text() and "samples=800" in out.read_text()
    assert json.loads((tmp_path / "r.json").read_text())["samples"] == 800
    assert "| store |" in summary.read_text()


def test_cli_without_traffic_still_reports(dc: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[str] = []
    monkeypatch.setattr(dc, "send_event", lambda report, conn, url: sent.append(report.status))
    monkeypatch.setenv("APPLICATIONINSIGHTS_CONNECTION_STRING", "InstrumentationKey=k")
    assert dc.main(["check", "--appinsights-app-id", "app"]) == 0
    assert sent == ["insufficient_data"]


def test_cli_requires_a_connection_string_to_send(dc: ModuleType) -> None:
    assert dc.main(["check", "--appinsights-app-id", "app"]) == 1
    assert dc.main(["check", "--appinsights-app-id", "app", "--no-event"]) == 0
