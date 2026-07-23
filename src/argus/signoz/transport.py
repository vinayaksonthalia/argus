"""The SigNoz access seam: one protocol, two implementations.

Every read ARGUS performs goes through `SignozTransport.query_range(payload,
tag)`. The `tag` is a stable logical name for the call (e.g. "golden.p99.after",
"verify.0") used for span naming and — critically — for replay: the
`ReplayTransport` serves `<fixture_dir>/responses/<tag>.json`, which makes
whole investigations replayable offline and turns recorded incidents into
eval cases.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import httpx

from ..telemetry import tracer


@dataclass
class QueryStats:
    """Per-investigation query-cost accumulator, fed by the
    `meta.{rowsScanned,bytesScanned,durationMs}` block SigNoz returns on every
    query_range response. ARGUS reports its own read footprint per RCA."""

    queries: int = 0
    rows_scanned: int = 0
    bytes_scanned: int = 0
    duration_ms: int = 0
    by_tag: dict[str, int] = field(default_factory=dict)  # tag -> rowsScanned

    def record(self, tag: str, envelope: dict[str, Any]) -> None:
        self.queries += 1
        meta = (envelope.get("data") or {}).get("meta") or {}
        rows = int(meta.get("rowsScanned", 0) or 0)
        self.rows_scanned += rows
        self.bytes_scanned += int(meta.get("bytesScanned", 0) or 0)
        self.duration_ms += int(meta.get("durationMs", 0) or 0)
        self.by_tag[tag] = self.by_tag.get(tag, 0) + rows

    def summary(self) -> str:
        mb = self.bytes_scanned / 1e6
        return (
            f"{self.queries} SigNoz queries · {self.rows_scanned:,} rows / "
            f"{mb:.1f} MB scanned · {self.duration_ms} ms query time"
        )


class SignozTransport(Protocol):
    stats: QueryStats

    def query_range(self, payload: dict[str, Any], tag: str) -> dict[str, Any]:
        """POST /api/v5/query_range. Returns the parsed JSON envelope."""
        ...


class HttpTransport:
    """Live SigNoz over REST with SIGNOZ-API-KEY header auth."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout, headers={"SIGNOZ-API-KEY": api_key}
        )
        self.stats = QueryStats()

    def query_range(self, payload: dict[str, Any], tag: str) -> dict[str, Any]:
        with tracer().start_as_current_span(f"signoz.query_range.{tag}") as span:
            span.set_attribute("argus.signoz.tag", tag)
            resp = self._client.post(f"{self._base}/api/v5/query_range", json=payload)
            span.set_attribute("http.status_code", resp.status_code)
            resp.raise_for_status()
            envelope = resp.json()
            self.stats.record(tag, envelope)
            meta = (envelope.get("data") or {}).get("meta") or {}
            span.set_attribute("argus.signoz.rows_scanned", int(meta.get("rowsScanned", 0) or 0))
            span.set_attribute("argus.signoz.bytes_scanned", int(meta.get("bytesScanned", 0) or 0))
            return envelope


class ReplayTransport:
    """Serves recorded responses from `<fixture_dir>/responses/<tag>.json`.

    Missing tags raise (a recorded incident must be complete) except for tags
    listed in `optional_missing.json`, which return an empty envelope — this
    models graceful degradation for evidence sources that were unavailable
    when the incident was recorded.
    """

    EMPTY = {"status": "success", "data": {"data": {"results": []}}}

    def __init__(self, fixture_dir: str | Path, lenient: bool = False) -> None:
        self._dir = Path(fixture_dir) / "responses"
        opt = Path(fixture_dir) / "optional_missing.json"
        self._optional: set[str] = set(json.loads(opt.read_text())) if opt.exists() else set()
        self.calls: list[str] = []  # recorded for test assertions
        self.stats = QueryStats()
        # lenient mode (provider benchmarking): a live LLM proposes its own
        # verification queries whose tags were never recorded — serve EMPTY
        # instead of failing, so different providers can run over the same
        # recorded evidence.
        self._lenient = lenient

    def query_range(self, payload: dict[str, Any], tag: str) -> dict[str, Any]:
        self.calls.append(tag)
        path = self._dir / f"{tag}.json"
        if not path.exists():
            if self._lenient or tag in self._optional or any(
                tag.startswith(p.rstrip("*")) for p in self._optional if p.endswith("*")
            ):
                return dict(self.EMPTY)
            raise FileNotFoundError(f"replay fixture missing response for tag '{tag}' ({path})")
        envelope = json.loads(path.read_text())
        self.stats.record(tag, envelope)
        return envelope
