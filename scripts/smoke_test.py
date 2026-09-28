"""Post-deploy smoke test against one revision's URL.

Run by deploy.yml against the canary revision's label URL before it gets any
real traffic, and usable by hand against any environment:

    python scripts/smoke_test.py --base-url https://<app>---canary.<env-domain> \
        --reference artifacts/canary_reference.json --expected-version <model_version>

Checks: readiness, model version, the forecast contract, a validation error,
and the canary reference (consistency with training output + plausibility vs
seasonal naive). Exit code 0 = pass.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml import canary


def call(base: str, method: str, path: str, body: Any = None, timeout: float = 30) -> tuple[int, Any, dict]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method)
    req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null"), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null"), dict(e.headers)


def wait_ready(base: str, timeout_s: int) -> None:
    deadline = time.monotonic() + timeout_s
    last: Any = None
    while time.monotonic() < deadline:
        try:
            status, body, _ = call(base, "GET", "/readyz", timeout=10)
            if status == 200:
                return
            last = (status, body)
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            last = exc
        time.sleep(5)
    raise SystemExit(f"not ready after {timeout_s}s: {last}")


def run(base: str, reference_path: Path, expected_version: str | None, ready_timeout: int) -> list[str]:
    failures: list[str] = []
    wait_ready(base, ready_timeout)

    status, info, _ = call(base, "GET", "/v1/model")
    if status != 200:
        return [f"/v1/model returned {status}"]
    if expected_version and info.get("model_version") != expected_version:
        failures.append(f"serving model {info.get('model_version')}, expected {expected_version}")

    status, body, _ = call(base, "POST", "/v1/forecast", {"store": 0, "item": 1, "start_date": "2018-01-01"})
    if status != 422:
        failures.append(f"invalid request returned {status}, expected 422")

    reference = json.loads(reference_path.read_text())
    served: list[list[float]] = []
    for case in reference["cases"]:
        status, body, headers = call(base, "POST", "/v1/forecast", case["request"])
        if status != 200:
            failures.append(f"{case['request']} returned {status}: {body}")
            served.append([])
            continue
        if not headers.get("X-Request-ID") and not headers.get("x-request-id"):
            failures.append("response is missing X-Request-ID")
        served.append([d["units"] for d in body["forecast"]])
    if not failures:
        failures += canary.check(reference, served)
    return failures


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", required=True)
    p.add_argument("--reference", type=Path, default=Path("artifacts/canary_reference.json"))
    p.add_argument("--expected-version", default=None)
    p.add_argument("--ready-timeout", type=int, default=180)
    a = p.parse_args()
    failures = run(a.base_url, a.reference, a.expected_version, a.ready_timeout)
    for f in failures:
        print(f"FAIL: {f}")
    print("smoke test " + ("FAILED" if failures else "passed") + f" against {a.base_url}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
