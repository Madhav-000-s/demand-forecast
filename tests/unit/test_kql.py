"""KQL hygiene: request telemetry is sampled, so counts over `requests` must be
weighted by itemCount (count() undercounts under load)."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
QUERIES = sorted((ROOT / "infra/modules/dashboard/queries").glob("*.kql"))


def _script_query(name: str, attr: str, monkeypatch: pytest.MonkeyPatch) -> str:
    spec = importlib.util.spec_from_file_location(name, ROOT / f"scripts/{name}.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, name, mod)
    spec.loader.exec_module(mod)
    return str(getattr(mod, attr))


def _alert_queries() -> list[str]:
    tf = (ROOT / "infra/modules/alerts/main.tf").read_text()
    return re.findall(r"<<-KQL\n(.*?)\n\s*KQL", tf, flags=re.S)


def unweighted_request_counts(kql: str) -> bool:
    uses_requests = re.search(r"^\s*(requests\b|\$\{local\.api_requests\})", kql, flags=re.M)
    return bool(uses_requests) and bool(re.search(r"\bcount\(\)|\bcountif\(", kql))


@pytest.mark.parametrize("path", QUERIES, ids=lambda p: p.name)
def test_dashboard_queries_weight_request_counts(path: Path) -> None:
    assert not unweighted_request_counts(path.read_text()), path.name


def test_alert_queries_weight_request_counts() -> None:
    queries = _alert_queries()
    assert len(queries) >= 3
    for q in queries:
        assert not unweighted_request_counts(q), q


def test_script_queries_weight_request_counts(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, attr in [("canary_analysis", "QUERY"), ("appinsights", "WINDOW_STATS")]:
        q = _script_query(name, attr, monkeypatch)
        assert "sum(itemCount)" in q and not unweighted_request_counts(q), name


def test_the_guard_catches_count() -> None:
    assert unweighted_request_counts("requests\n| summarize n = count()")
    assert not unweighted_request_counts("traces\n| summarize n = count()")
