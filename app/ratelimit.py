"""Per-client rate limiting for the public /v1 endpoints.

The API is public with no authentication, so each client IP gets a token
bucket: ``RATE_LIMIT_RPS`` requests per second sustained, bursts up to
``RATE_LIMIT_BURST``. Over the limit the API answers 429 with Retry-After.

Limits are per replica (state lives in memory), so the effective limit for
one client is up to N times higher with N replicas. That bounds abuse and
cost without a gateway; a shared limit would need Redis or API Management.

Our own deploy and drill traffic (canary analysis, smoke tests, k6 load
tests) comes from one GitHub runner IP at rates a real client never needs.
It sends ``X-Ops-Token``, compared in constant time with ``OPS_BYPASS_TOKEN``
(a Key Vault secret); no token configured means no bypass.

Client IP: Container Apps' Envoy appends the peer address to
X-Forwarded-For, so the right-most entry is the address Envoy saw. Left-most
entries are whatever the client sent and can be forged.
"""

from __future__ import annotations

import hmac
import math
import os
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass

from starlette.requests import Request


@dataclass
class Decision:
    allowed: bool
    retry_after_s: int = 0


class RateLimiter:
    def __init__(
        self,
        rate_per_s: float,
        burst: int,
        max_clients: int = 10_000,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.rate = rate_per_s
        self.burst = float(burst)
        self.max_clients = max_clients
        self.clock = clock
        self._buckets: OrderedDict[str, tuple[float, float]] = OrderedDict()  # key -> (tokens, last)

    @property
    def enabled(self) -> bool:
        return self.rate > 0 and self.burst > 0

    def check(self, key: str) -> Decision:
        if not self.enabled:
            return Decision(True)
        now = self.clock()
        tokens, last = self._buckets.pop(key, (self.burst, now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens >= 1.0:
            self._remember(key, tokens - 1.0, now)
            return Decision(True)
        self._remember(key, tokens, now)
        return Decision(False, max(1, math.ceil((1.0 - tokens) / self.rate)))

    def _remember(self, key: str, tokens: float, now: float) -> None:
        self._buckets[key] = (tokens, now)  # most recent last
        while len(self._buckets) > self.max_clients:  # bounded memory under IP floods
            self._buckets.popitem(last=False)

    @classmethod
    def from_env(cls) -> RateLimiter:
        return cls(
            float(os.environ.get("RATE_LIMIT_RPS", "10")), int(os.environ.get("RATE_LIMIT_BURST", "50"))
        )


def client_key(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        last = forwarded.split(",")[-1].strip()
        if last:
            return last
    return request.client.host if request.client else "unknown"


def has_ops_token(request: Request, expected: str | None = None) -> bool:
    expected = os.environ.get("OPS_BYPASS_TOKEN", "") if expected is None else expected
    supplied = request.headers.get("x-ops-token", "")
    return bool(expected) and bool(supplied) and hmac.compare_digest(supplied, expected)
