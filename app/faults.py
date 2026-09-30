"""Fault injection for release drills.

A drill image is the production image plus ``artifacts/fault.json``; normal
images never contain the file, so production behaviour cannot be switched on
by configuration. Supported faults:

    {"extra_latency_ms": 400}   add a delay to every /v1 request

The delay runs inside the request, so App Insights records it as request
duration, exactly like a real slow release would appear.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("dfcast.faults")

MAX_LATENCY_MS = 5_000


@dataclass(frozen=True)
class Faults:
    extra_latency_ms: int = 0

    @property
    def active(self) -> bool:
        return self.extra_latency_ms > 0


def load(artifact_dir: str | Path) -> Faults:
    path = Path(artifact_dir) / "fault.json"
    if not path.is_file():
        return Faults()
    try:
        spec = json.loads(path.read_text())
        latency = int(spec.get("extra_latency_ms", 0))
    except (ValueError, TypeError, AttributeError):
        log.error("ignoring malformed fault.json", extra={"fault_file": str(path)})
        return Faults()
    faults = Faults(extra_latency_ms=min(max(latency, 0), MAX_LATENCY_MS))
    if faults.active:
        latency = faults.extra_latency_ms
        log.warning("FAULT INJECTION ACTIVE (drill image)", extra={"extra_latency_ms": latency})
    return faults
