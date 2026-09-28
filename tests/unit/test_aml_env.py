"""Keep the Azure ML training environment in sync with requirements/train.txt."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def pins(lines: list[str]) -> dict[str, str]:
    out = {}
    for line in lines:
        m = re.match(r"^\s*-?\s*([A-Za-z0-9_.\-\[\]]+)==([^\s#]+)", line)
        if m:
            out[m.group(1).split("[")[0].lower()] = m.group(2)
    return out


def test_conda_pins_match_training_requirements() -> None:
    conda = yaml.safe_load((ROOT / "ml/aml/conda.yml").read_text())
    pip_section = next(d for d in conda["dependencies"] if isinstance(d, dict))["pip"]
    conda_pins = pins(pip_section)
    req = pins((ROOT / "requirements/train.txt").read_text().splitlines())
    req.update(pins((ROOT / "requirements/app.txt").read_text().splitlines()))
    for pkg in ("lightgbm", "numpy", "pandas"):
        assert conda_pins[pkg] == req[pkg], pkg


def test_job_uses_registered_data_and_cluster() -> None:
    job = yaml.safe_load((ROOT / "ml/aml/train-job.yml").read_text())
    assert job["inputs"]["data"]["path"] == "azureml:store-item-sales@latest"
    assert job["compute"] == "azureml:cpu-cluster"
    assert "${{outputs.model}}" in job["command"]
