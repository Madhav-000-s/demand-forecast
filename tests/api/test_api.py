"""API contract tests against a model trained on synthetic data."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import lightgbm as lgb
import numpy as np
import pytest
from fastapi.testclient import TestClient

from app import logging_setup
from app.main import app
from ml import data as data_mod
from ml.train import features_and_target, from_target


@pytest.fixture(scope="module")
def client(artifacts: Path) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("ARTIFACT_DIR", str(artifacts))
    with TestClient(app) as c:
        yield c
    mp.undo()


def body(**overrides: object) -> dict:
    return {"store": 1, "item": 2, "start_date": "2018-01-01", "horizon_days": 14, **overrides}


def test_probes(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"status": "ok"}
    ready = client.get("/readyz")
    assert ready.status_code == 200 and ready.json() == {"status": "ready"}


def test_forecast_contract(client: TestClient) -> None:
    r = client.post("/v1/forecast", json=body())
    assert r.status_code == 200
    data = r.json()
    assert set(data) == {"store", "item", "model_version", "forecast"}
    assert data["model_version"] == "test-1"
    assert len(data["forecast"]) == 14
    assert data["forecast"][0]["date"] == "2018-01-01"
    assert data["forecast"][-1]["date"] == "2018-01-14"
    assert all(day["units"] >= 0 for day in data["forecast"])
    assert r.headers["X-Model-Version"] == "test-1"
    assert r.headers["X-Request-ID"]


def test_request_id_is_echoed(client: TestClient) -> None:
    r = client.post("/v1/forecast", json=body(), headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"


def test_serving_matches_training_features(client: TestClient, synthetic_csv: Path, artifacts: Path) -> None:
    """Train/serve parity: the API must predict what the model predicts on training-built features."""
    panel = data_mod.to_panel(data_mod.load_csv(synthetic_csv))
    x, _ = features_and_target(panel, date(2017, 12, 1), date(2017, 12, 10))
    row = list(zip(panel.stores, panel.items, strict=True)).index((2, 3))
    x_series = x[row * 10 : (row + 1) * 10]
    expected = from_target(lgb.Booster(model_file=str(artifacts / "model.txt")).predict(x_series))

    r = client.post("/v1/forecast", json=body(store=2, item=3, start_date="2017-12-01", horizon_days=10))
    got = [d["units"] for d in r.json()["forecast"]]
    np.testing.assert_allclose(got, np.round(expected, 2), atol=0.006)


def test_last_servable_day(client: TestClient) -> None:
    # history ends 2017-12-31, so the last servable day is 91 days later
    ok = client.post("/v1/forecast", json=body(start_date="2018-04-01", horizon_days=1))
    assert ok.status_code == 200
    too_far = client.post("/v1/forecast", json=body(start_date="2018-03-25", horizon_days=10))
    assert too_far.status_code == 422
    assert too_far.json()["detail"][0]["loc"] == ["body", "start_date"]


@pytest.mark.parametrize(
    ("override", "field"),
    [
        ({"store": 0}, "store"),
        ({"store": 11}, "store"),
        ({"item": 51}, "item"),
        ({"horizon_days": 0}, "horizon_days"),
        ({"horizon_days": 91}, "horizon_days"),
        ({"start_date": "not-a-date"}, "start_date"),
        ({"start_date": "2010-01-01"}, "start_date"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_validation_errors_are_422_with_field(client: TestClient, override: dict, field: str) -> None:
    r = client.post("/v1/forecast", json=body(**override))
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"][-1] == field


def test_unknown_series_is_422(client: TestClient) -> None:
    # valid ids, but the synthetic model only has stores 1-2 / items 1-3
    r = client.post("/v1/forecast", json=body(store=9, item=40))
    assert r.status_code == 422


def test_batch(client: TestClient) -> None:
    reqs = [body(store=s, item=i, horizon_days=3) for s in (1, 2) for i in (1, 2, 3)]
    r = client.post("/v1/forecast/batch", json={"requests": reqs})
    assert r.status_code == 200
    results = r.json()["results"]
    assert [(x["store"], x["item"]) for x in results] == [(s, i) for s in (1, 2) for i in (1, 2, 3)]
    assert all(len(x["forecast"]) == 3 for x in results)


def test_batch_limits(client: TestClient) -> None:
    assert client.post("/v1/forecast/batch", json={"requests": []}).status_code == 422
    too_many = {"requests": [body()] * 51}
    assert client.post("/v1/forecast/batch", json=too_many).status_code == 422
    bad_item = {"requests": [body(), body(start_date="2030-01-01")]}
    r = client.post("/v1/forecast/batch", json=bad_item)
    assert r.status_code == 422
    assert r.json()["detail"][0]["loc"] == ["body", "requests", 1, "start_date"]


def test_model_info(client: TestClient) -> None:
    info = client.get("/v1/model").json()
    assert info["model_version"] == "test-1"
    assert info["history_end"] == "2017-12-31"
    assert info["servable_to"] == "2018-04-01"
    assert info["test_smape"] < info["baseline_seasonal_naive_smape"]


def test_feature_log_line(client: TestClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO, logger="dfcast.features"):
        client.post("/v1/forecast", json=body(), headers={"X-Request-ID": "drift-1"})
    records = [r for r in caplog.records if r.name == "dfcast.features"]
    assert records
    rec = records[-1]
    assert rec.request_id == "drift-1"  # type: ignore[attr-defined]
    # flat scalar attributes only: App Insights stores them as customDimensions
    extras = logging_setup.extra_fields(rec)
    assert all(isinstance(v, (str, int, float)) for v in extras.values()), extras
    features = json.loads(rec.features_json)  # type: ignore[attr-defined]
    assert set(features) >= {"store", "item", "lag_91", "dow_mean_1y"}


@pytest.mark.parametrize(
    ("header", "expected"),
    [(None, "user"), ("canary", "canary"), ("Drill", "drill"), ("bad value!", "user"), ("x" * 40, "user")],
)
def test_traffic_source_is_logged(
    client: TestClient, caplog: pytest.LogCaptureFixture, header: str | None, expected: str
) -> None:
    headers = {"X-Traffic-Source": header} if header else {}
    with caplog.at_level(logging.INFO, logger="dfcast"):
        client.post("/v1/forecast", json=body(), headers=headers)
    feature_rec = [r for r in caplog.records if r.name == "dfcast.features"][-1]
    request_rec = [r for r in caplog.records if r.getMessage() == "request"][-1]
    assert feature_rec.traffic_source == expected  # type: ignore[attr-defined]
    assert request_rec.traffic_source == expected  # type: ignore[attr-defined]


def test_json_log_line_carries_extra_fields() -> None:
    rec = logging.LogRecord("dfcast.api", logging.INFO, __file__, 1, "request", (), None)
    rec.request_id = "abc"
    rec.status = 200
    line = json.loads(logging_setup.JsonFormatter().format(rec))
    assert line["msg"] == "request" and line["request_id"] == "abc" and line["status"] == 200
    assert "args" not in line and "levelno" not in line


def test_openapi_lists_endpoints(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/v1/forecast", "/v1/forecast/batch", "/v1/model", "/healthz", "/readyz"} <= set(paths)


def test_not_ready_without_artifacts(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path / "missing"))
    with TestClient(app) as c:
        assert c.get("/healthz").status_code == 200
        assert c.get("/readyz").status_code == 503
        assert c.post("/v1/forecast", json=body()).status_code == 503
