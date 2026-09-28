from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from ml import gate
from ml.metrics import mae, smape


def test_smape_known_values() -> None:
    assert smape(np.array([100.0]), np.array([100.0])) == 0.0
    assert smape(np.array([100.0]), np.array([0.0])) == pytest.approx(200.0)
    assert smape(np.array([100.0]), np.array([50.0])) == pytest.approx(200 * 50 / 150)


def test_smape_both_zero_counts_as_perfect() -> None:
    assert smape(np.array([0.0, 10.0]), np.array([0.0, 10.0])) == 0.0


def test_mae() -> None:
    assert mae(np.array([1.0, 2.0, 3.0]), np.array([2.0, 2.0, 5.0])) == pytest.approx(1.0)


def metrics(model: float, naive: float) -> dict:
    return {"model": {"smape": model}, "baselines": {"seasonal_naive": {"smape": naive}}}


@pytest.mark.parametrize(
    ("cand", "naive", "prod", "passes"),
    [
        (12.0, 18.0, None, True),  # beats naive, no production model yet
        (19.0, 18.0, None, False),  # loses to naive
        (12.2, 18.0, 12.0, True),  # 1.7% worse than production: within tolerance
        (12.3, 18.0, 12.0, False),  # 2.5% worse: rejected
        (11.0, 18.0, 12.0, True),  # better than production
    ],
)
def test_gate_rules(cand: float, naive: float, prod: float | None, passes: bool) -> None:
    result = gate.evaluate(metrics(cand, naive), metrics(prod, naive) if prod else None)
    assert result.passed is passes
    assert ("PASSED" in result.summary) is passes


def test_gate_cli_exit_codes(tmp_path: Path) -> None:
    good, bad = tmp_path / "good.json", tmp_path / "bad.json"
    good.write_text(json.dumps(metrics(12.0, 18.0)))
    bad.write_text(json.dumps(metrics(20.0, 18.0)))
    assert gate.main(["--candidate", str(good)]) == 0
    assert gate.main(["--candidate", str(bad)]) == 1
    assert gate.main(["--candidate", str(good), "--production", str(good)]) == 0
