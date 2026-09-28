from __future__ import annotations

import json
from pathlib import Path

import pytest

from app import telemetry
from ml import canary


@pytest.fixture(scope="module")
def reference(artifacts: Path) -> dict:
    return json.loads((artifacts / "canary_reference.json").read_text())


def served_from(reference: dict, scale: float = 1.0) -> list[list[float]]:
    return [[round(v * scale, 2) for v in c["expected"]] for c in reference["cases"]]


def test_reference_shape(reference: dict) -> None:
    assert 1 <= len(reference["cases"]) <= canary.N_INPUTS
    case = reference["cases"][0]
    assert case["request"]["start_date"] == "2018-01-01"  # day after the data ends
    assert len(case["expected"]) == len(case["seasonal_naive"]) == canary.HORIZON
    assert reference["model_smape_vs_seasonal_naive"] < canary.PLAUSIBILITY_MAX_SMAPE


def test_the_trained_model_passes(reference: dict) -> None:
    assert canary.check(reference, served_from(reference)) == []


def test_a_different_model_fails_consistency(reference: dict) -> None:
    failures = canary.check(reference, served_from(reference, 1.05))
    assert failures and "differs from training output" in failures[0]


def test_a_constant_model_fails_plausibility(reference: dict) -> None:
    constant = [[1.0] * canary.HORIZON for _ in reference["cases"]]
    assert canary.plausibility_only(reference, constant)
    # even if it were the model training produced (consistent), it is implausible
    fake = {**reference, "cases": [{**c, "expected": [1.0] * canary.HORIZON} for c in reference["cases"]]}
    assert any("plausibility" in f for f in canary.check(fake, constant))


def test_wrong_number_of_responses(reference: dict) -> None:
    assert canary.check(reference, [])


def test_telemetry_is_off_without_connection_string(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APPLICATIONINSIGHTS_CONNECTION_STRING", raising=False)
    assert telemetry.configure() is False


def test_resource_attributes_carry_the_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CONTAINER_APP_REVISION", "ca-dfcast-prod-cin--g1234567-m3-9")
    monkeypatch.setenv("CONTAINER_APP_REPLICA_NAME", "ca-dfcast-prod-cin--g1234567-m3-9-abc")
    attrs = telemetry.resource_attributes()
    assert attrs["service.version"] == "ca-dfcast-prod-cin--g1234567-m3-9"
    assert attrs["service.instance.id"].startswith(attrs["service.version"])
    assert attrs["service.name"] == "dfcast-api"
