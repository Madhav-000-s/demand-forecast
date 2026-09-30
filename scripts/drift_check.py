"""Drift check: PSI of recent request features against the served model's reference.

Runs every 6 hours from .github/workflows/drift.yml:

    python scripts/drift_check.py served-version --appinsights-app-id <id> --hours 6
    python scripts/drift_check.py check --appinsights-app-id <id> --model-version <v> \
        --reference reference_stats.json --hours 6 --report drift_report.json

``served-version`` prints the model version that answered most requests in the
window (empty if there was no traffic). ``check`` pulls the feature vectors
that version logged (the API writes one ``forecast_features`` trace per
forecast), computes the Population Stability Index of each monitored feature
against the model's ``reference_stats.json``, and writes a ``drift_check``
custom event to Application Insights. The drift alert and the dashboard read
that event.

Monitored features are store, item and the six history features. Calendar
features are left out: they say which dates were requested, which is shown on
the dashboard but is not a property of the data the model learned from.
Synthetic traffic from deploys (``X-Traffic-Source: canary`` or ``smoke``) is
excluded.

Status: ``drift`` when any monitored feature has PSI above the threshold with
at least ``--min-samples`` requests; ``insufficient_data`` below that (PSI of
a 50-category feature over 200 samples is ~0.3 from sampling noise alone);
otherwise ``ok``. Needs an Azure CLI login; sending the event needs
APPLICATIONINSIGHTS_CONNECTION_STRING.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import appinsights  # scripts/ sibling module

from ml.drift_stats import feature_psi
from ml.features import CATEGORICAL_FEATURES, HISTORY_FEATURES

MONITORED = CATEGORICAL_FEATURES + HISTORY_FEATURES
EXCLUDED_SOURCES = ("canary", "smoke")
ROLE = "dfcast-drift-job"
_VERSION_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")

_BASE = """
traces
| where timestamp > ago({hours}h)
| where message == 'forecast_features'
| extend source = tostring(customDimensions.traffic_source),
         model_version = tostring(customDimensions.model_version)
| where source !in ({excluded})
"""
QUERY_VERSIONS = _BASE + "| summarize n = count() by model_version\n| order by n desc"
QUERY_FEATURES = (
    _BASE
    + "| where model_version == '{version}'\n"
    + "| project features = tostring(customDimensions.features_json)\n"
    + "| take {limit}"
)


@dataclass
class Report:
    status: str
    model_version: str
    window_hours: int
    samples: int
    threshold: float
    min_samples: int
    psi: dict[str, float] = field(default_factory=dict)
    drifted: list[str] = field(default_factory=list)

    @property
    def max_feature(self) -> str:
        return max(self.psi, key=lambda k: self.psi[k]) if self.psi else ""

    @property
    def max_psi(self) -> float:
        return max(self.psi.values()) if self.psi else 0.0


def run_query(app_id: str, query: str) -> list[list[Any]]:
    return appinsights.query(app_id, query)


def _excluded() -> str:
    return ", ".join(f"'{s}'" for s in EXCLUDED_SOURCES)


def served_version(app_id: str, hours: int) -> str:
    rows = run_query(app_id, QUERY_VERSIONS.format(hours=hours, excluded=_excluded()))
    versions = [str(r[0]) for r in rows if r and r[0]]
    return versions[0] if versions else ""


def fetch_features(app_id: str, version: str, hours: int, limit: int = 50_000) -> list[dict[str, float]]:
    if not _VERSION_RE.fullmatch(version):
        raise ValueError(f"unexpected model version {version!r}")
    query = QUERY_FEATURES.format(hours=hours, excluded=_excluded(), version=version, limit=limit)
    out = []
    for (raw,) in run_query(app_id, query):
        try:
            out.append(json.loads(raw))
        except (TypeError, json.JSONDecodeError):
            continue  # a malformed line must not sink the whole check
    return out


def evaluate(
    reference: dict[str, Any],
    rows: list[dict[str, float]],
    *,
    model_version: str,
    hours: int,
    threshold: float,
    min_samples: int,
) -> Report:
    report = Report("insufficient_data", model_version, hours, len(rows), threshold, min_samples)
    if not rows:
        return report
    for name in MONITORED:
        values = np.array([r.get(name, np.nan) for r in rows], dtype=np.float64)
        report.psi[name] = round(feature_psi(reference[name], values), 4)
    report.drifted = sorted((k for k, v in report.psi.items() if v > threshold), key=lambda k: -report.psi[k])
    if len(rows) >= min_samples:
        report.status = "drift" if report.drifted else "ok"
    return report


parse_connection_string = appinsights.parse_connection_string


def event_properties(report: Report, run_url: str = "") -> tuple[dict[str, str], dict[str, float]]:
    measurements = {"samples": float(report.samples), "max_psi": report.max_psi}
    measurements.update({f"psi_{k}": v for k, v in report.psi.items()})
    properties = {
        "status": report.status,
        "model_version": report.model_version,
        "max_feature": report.max_feature,
        "drifted": ",".join(report.drifted),
        "window_hours": str(report.window_hours),
        "threshold": str(report.threshold),
        "min_samples": str(report.min_samples),
        "run_url": run_url,
    }
    return properties, measurements


def event_envelope(report: Report, ikey: str, run_url: str = "") -> dict[str, Any]:
    properties, measurements = event_properties(report, run_url)
    return appinsights.event_envelope("drift_check", properties, measurements, ikey, ROLE)


def send_event(report: Report, connection_string: str, run_url: str = "") -> None:
    properties, measurements = event_properties(report, run_url)
    appinsights.send_event(connection_string, "drift_check", properties, measurements, ROLE)


def markdown(report: Report) -> str:
    verdict = {
        "drift": f"**Drift**: {', '.join(report.drifted)} above PSI {report.threshold}",
        "ok": f"**OK**: every monitored feature at or below PSI {report.threshold}",
        "insufficient_data": f"**Not enough traffic**: {report.samples} requests (< {report.min_samples}); "
        "PSI shown for information only",
    }[report.status]
    lines = [
        f"### Drift check: model `{report.model_version or 'none'}`, last {report.window_hours} h\n",
        verdict + "\n",
    ]
    if report.psi:
        lines += ["| feature | PSI |", "|---|---|"]
        lines += [f"| {k} | {v:.3f}{' ⚠' if k in report.drifted else ''} |" for k, v in report.psi.items()]
    return "\n".join(lines)


def _write_github(report: Report) -> None:
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"status={report.status}\nmax_psi={report.max_psi}\n")
            f.write(f"max_feature={report.max_feature}\nsamples={report.samples}\n")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(markdown(report) + "\n")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    sv = sub.add_parser("served-version", help="model version with the most requests in the window")
    ck = sub.add_parser("check", help="compute PSI and send the drift_check event")
    for s in (sv, ck):
        s.add_argument("--appinsights-app-id", required=True)
        s.add_argument("--hours", type=int, default=6)
    ck.add_argument("--model-version", default="", help="empty = no traffic; reports insufficient_data")
    ck.add_argument("--reference", type=Path, help="reference_stats.json of that model version")
    ck.add_argument("--threshold", type=float, default=0.25)
    ck.add_argument("--min-samples", type=int, default=500)
    ck.add_argument("--report", type=Path, help="write the report as JSON")
    ck.add_argument("--no-event", action="store_true", help="do not send the App Insights event")
    a = p.parse_args(argv)

    if a.cmd == "served-version":
        print(served_version(a.appinsights_app_id, a.hours))
        return 0

    rows: list[dict[str, float]] = []
    reference: dict[str, Any] = {}
    if a.model_version:
        if a.reference is None:
            p.error("--reference is required with --model-version")
        reference = json.loads(a.reference.read_text())
        rows = fetch_features(a.appinsights_app_id, a.model_version, a.hours)
    report = evaluate(
        reference, rows, model_version=a.model_version, hours=a.hours,
        threshold=a.threshold, min_samples=a.min_samples,
    )  # fmt: skip
    print(markdown(report))
    if a.report:
        a.report.write_text(json.dumps({**asdict(report), "max_psi": report.max_psi}, indent=2))
    _write_github(report)
    if not a.no_event:
        conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING", "")
        if not conn:
            print("APPLICATIONINSIGHTS_CONNECTION_STRING not set; use --no-event to skip", file=sys.stderr)
            return 1
        run_url = ""
        if os.environ.get("GITHUB_RUN_ID"):
            run_url = (
                f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/"
                f"{os.environ.get('GITHUB_REPOSITORY', '')}/actions/runs/{os.environ['GITHUB_RUN_ID']}"
            )
        send_event(report, conn, run_url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
