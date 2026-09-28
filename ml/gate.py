"""Promotion gate: decide whether a candidate model may be released.

A candidate passes when its test SMAPE
  1. beats the seasonal-naive baseline, and
  2. is no more than ``--tolerance`` (default 2%) worse than production.

Usage:
    python -m ml.gate --candidate artifacts/metrics.json [--production prod/metrics.json]

Exit code 0 = promote, 1 = reject. A markdown summary is printed (and appended
to $GITHUB_STEP_SUMMARY when running in GitHub Actions).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GateResult:
    passed: bool
    reasons: list[str]
    summary: str


def evaluate(candidate: dict, production: dict | None, tolerance: float = 0.02) -> GateResult:
    cand = candidate["model"]["smape"]
    naive = candidate["baselines"]["seasonal_naive"]["smape"]
    reasons: list[str] = []
    rows = [
        "| check | candidate SMAPE | reference SMAPE | result |",
        "|---|---|---|---|",
    ]

    beats_naive = cand < naive
    rows.append(f"| beats seasonal naive | {cand:.4f} | {naive:.4f} | {'pass' if beats_naive else 'FAIL'} |")
    if not beats_naive:
        reasons.append(f"SMAPE {cand:.4f} does not beat seasonal naive {naive:.4f}")

    if production is not None:
        prod = production["model"]["smape"]
        limit = prod * (1 + tolerance)
        ok = cand <= limit
        rows.append(
            f"| within {tolerance:.0%} of production | {cand:.4f} | {prod:.4f} (limit {limit:.4f}) "
            f"| {'pass' if ok else 'FAIL'} |"
        )
        if not ok:
            reasons.append(f"SMAPE {cand:.4f} is more than {tolerance:.0%} worse than production {prod:.4f}")
    else:
        rows.append("| within tolerance of production | - | no production model | skipped |")

    passed = not reasons
    header = f"### Promotion gate: {'PASSED' if passed else 'REJECTED'}"
    return GateResult(passed, reasons, "\n".join([header, "", *rows]))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Model promotion gate")
    p.add_argument("--candidate", type=Path, required=True)
    p.add_argument("--production", type=Path, default=None)
    p.add_argument("--tolerance", type=float, default=0.02)
    args = p.parse_args(argv)

    candidate = json.loads(args.candidate.read_text())
    production = json.loads(args.production.read_text()) if args.production else None
    result = evaluate(candidate, production, args.tolerance)

    print(result.summary)
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(result.summary + "\n")
    for reason in result.reasons:
        print(f"rejected: {reason}", file=sys.stderr)
    return 0 if result.passed else 1


if __name__ == "__main__":
    sys.exit(main())
