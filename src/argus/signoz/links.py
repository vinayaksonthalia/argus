"""Deep-link factory: every RCA claim links to the exact SigNoz view backing it
(spec risk R3 — formats verified against SigNoz Community Edition ~v0.9x)."""

from __future__ import annotations

import json
from urllib.parse import quote

from ..models import TimeWindow


class LinkFactory:
    def __init__(self, base_url: str) -> None:
        self._base = base_url.rstrip("/")

    def trace(self, trace_id: str, span_id: str = "") -> str:
        url = f"{self._base}/trace/{trace_id}"
        if span_id:
            url += f"?spanId={quote(span_id)}"
        return url

    def logs_explorer(self, filter_expression: str, window: TimeWindow) -> str:
        """Logs explorer pre-filtered with an expression and pinned time range."""
        panel = quote(json.dumps({"expression": filter_expression}), safe="")
        return (
            f"{self._base}/logs/logs-explorer?"
            f"startTime={window.start_ms}&endTime={window.end_ms}"
            f"&filter={panel}"
        )

    def traces_explorer(self, filter_expression: str, window: TimeWindow) -> str:
        panel = quote(json.dumps({"expression": filter_expression}), safe="")
        return (
            f"{self._base}/traces-explorer?"
            f"startTime={window.start_ms}&endTime={window.end_ms}"
            f"&filter={panel}"
        )

    def service_overview(self, service: str, window: TimeWindow) -> str:
        return (
            f"{self._base}/services/{quote(service)}?"
            f"startTime={window.start_ms}&endTime={window.end_ms}"
        )
