"""Per-client rate limiting on /v1 (app/ratelimit.py)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.requests import Request

from app import ratelimit
from app.main import app

BODY = {"store": 1, "item": 1, "start_date": "2018-01-01", "horizon_days": 3}


class FakeClock:
    def __init__(self) -> None:
        self.t = 1000.0

    def __call__(self) -> float:
        return self.t


def test_bucket_allows_a_burst_then_refills() -> None:
    clock = FakeClock()
    rl = ratelimit.RateLimiter(rate_per_s=2, burst=3, clock=clock)
    assert [rl.check("a").allowed for _ in range(4)] == [True, True, True, False]
    assert rl.check("a").retry_after_s == 1
    assert rl.check("b").allowed  # clients are independent
    clock.t += 0.5  # +1 token at 2/s
    assert rl.check("a").allowed and not rl.check("a").allowed
    clock.t += 100  # refills only up to the burst
    assert sum(rl.check("a").allowed for _ in range(10)) == 3


def test_disabled_limiter_allows_everything() -> None:
    rl = ratelimit.RateLimiter(rate_per_s=0, burst=50)
    assert not rl.enabled and all(rl.check("a").allowed for _ in range(1000))


def test_memory_is_bounded() -> None:
    rl = ratelimit.RateLimiter(rate_per_s=1, burst=1, max_clients=100)
    for i in range(1000):
        rl.check(f"10.0.{i // 256}.{i % 256}")
    assert len(rl._buckets) == 100


def _request(headers: dict[str, str], client: tuple[str, int] | None = ("1.2.3.4", 5)) -> Request:
    scope = {
        "type": "http",
        "headers": [(k.lower().encode(), v.encode()) for k, v in headers.items()],
        "client": client,
    }
    return Request(scope)


def test_client_key_uses_the_proxy_appended_address() -> None:
    assert ratelimit.client_key(_request({"X-Forwarded-For": "6.6.6.6, 203.0.113.9"})) == "203.0.113.9"
    assert ratelimit.client_key(_request({})) == "1.2.3.4"
    assert ratelimit.client_key(_request({}, client=None)) == "unknown"


def test_ops_token() -> None:
    assert ratelimit.has_ops_token(_request({"X-Ops-Token": "s3cret"}), expected="s3cret")
    assert not ratelimit.has_ops_token(_request({"X-Ops-Token": "wrong"}), expected="s3cret")
    assert not ratelimit.has_ops_token(_request({}), expected="s3cret")
    assert not ratelimit.has_ops_token(_request({"X-Ops-Token": ""}), expected="")  # no token configured


@pytest.fixture
def limited(artifacts: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("ARTIFACT_DIR", str(artifacts))
    monkeypatch.setenv("RATE_LIMIT_RPS", "0.001")  # effectively no refill during the test
    monkeypatch.setenv("RATE_LIMIT_BURST", "3")
    monkeypatch.setenv("OPS_BYPASS_TOKEN", "drill-token")
    with TestClient(app) as c:
        yield c


def test_api_returns_429_with_retry_after(limited: TestClient) -> None:
    codes = [limited.post("/v1/forecast", json=BODY).status_code for _ in range(4)]
    assert codes == [200, 200, 200, 429]
    r = limited.get("/v1/model")
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1 and r.headers["X-Request-ID"]
    assert r.json() == {"detail": "rate limit exceeded"}


def test_probes_are_never_limited(limited: TestClient) -> None:
    for _ in range(5):
        limited.get("/v1/model")
    assert all(limited.get("/healthz").status_code == 200 for _ in range(20))
    assert limited.get("/readyz").status_code == 200


def test_ops_token_bypasses_and_other_clients_are_separate(limited: TestClient) -> None:
    for _ in range(5):
        limited.get("/v1/model")
    ok = [limited.get("/v1/model", headers={"X-Ops-Token": "drill-token"}).status_code for _ in range(10)]
    assert set(ok) == {200}
    assert limited.get("/v1/model", headers={"X-Ops-Token": "guess"}).status_code == 429
    other = {"X-Forwarded-For": "198.51.100.7"}
    assert limited.get("/v1/model", headers=other).status_code == 200
