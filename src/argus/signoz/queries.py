"""SigNoz Query Builder v5 payload factories and response parsing.

Every statistical read is a `/api/v5/query_range` builder-spec payload
(`compositeQuery.queries[].spec`). Payload construction is centralized here so
unit tests can assert the exact JSON against golden files (spec risk R2), and
so the verify node can only build *whitelisted* query shapes from
model-supplied params (NFR-7).
"""

from __future__ import annotations

import re
from typing import Any

from ..models import TimeWindow

# Whitelist for aggregation expressions the model may request in verification
# specs. Anything else is rejected before a query is built.
SAFE_AGGREGATION_RE = re.compile(
    r"^(count\(\)|count_distinct\([\w.]+\)|(p50|p90|p95|p99|avg|min|max|sum|rate)"
    r"\([\w.]+\))$"
)

# Filter expressions: conservative charset — identifiers, quoted strings,
# comparison/boolean operators. No parens-free injection surface beyond what
# the query API itself parses.
SAFE_FILTER_RE = re.compile(r"^[\w.\s'\"=!<>()\-:/,%*\[\]]+$")


def validate_verification_params(signal: str, aggregation: str, filter_expression: str) -> None:
    # metrics excluded: v5 metrics need object aggregations (metricName/
    # timeAggregation), not expression strings — a model-proposed metrics
    # check would always 400. Traces/logs cover every falsifiable check the
    # hypothesizer is prompted to produce.
    if signal not in ("traces", "logs"):
        raise ValueError(f"verification signal '{signal}' not allowed")
    if aggregation and not SAFE_AGGREGATION_RE.match(aggregation):
        raise ValueError(f"verification aggregation '{aggregation}' not in whitelist")
    if filter_expression and not SAFE_FILTER_RE.match(filter_expression):
        raise ValueError("verification filter expression contains disallowed characters")


def builder_payload(
    window: TimeWindow,
    specs: list[dict[str, Any]],
    request_type: str = "time_series",
) -> dict[str, Any]:
    """Envelope for /api/v5/query_range with one or more builder queries."""
    return {
        "schemaVersion": "v1",
        "start": window.start_ms,
        "end": window.end_ms,
        "requestType": request_type,
        "compositeQuery": {
            "queries": [{"type": "builder_query", "spec": spec} for spec in specs]
        },
        "formatOptions": {"formatTableResultForUI": False, "fillGaps": False},
    }


def _spec(
    name: str,
    signal: str,
    aggregation: str,
    filter_expression: str,
    step: int = 60,
) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": name,
        "signal": signal,
        "aggregations": [{"expression": aggregation}],
        "stepInterval": step,
        "disabled": False,
    }
    if filter_expression:
        spec["filter"] = {"expression": filter_expression}
    return spec


def p99_latency_payload(service: str, window: TimeWindow) -> dict[str, Any]:
    return builder_payload(
        window,
        [_spec("A", "traces", "p99(duration_nano)", f"service.name = '{service}'")],
    )


def error_rate_payload(service: str, window: TimeWindow) -> dict[str, Any]:
    """Two queries: errored span count (A) and total span count (B); rate is
    computed client-side as sum(A)/sum(B)."""
    return builder_payload(
        window,
        [
            _spec("A", "traces", "count()", f"service.name = '{service}' AND has_error = true"),
            _spec("B", "traces", "count()", f"service.name = '{service}'"),
        ],
    )


def throughput_payload(service: str, window: TimeWindow) -> dict[str, Any]:
    return builder_payload(
        window,
        [_spec("A", "traces", "count()", f"service.name = '{service}'")],
    )


def raw_traces_payload(filter_expression: str, window: TimeWindow, limit: int = 20) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": "A",
        "signal": "traces",
        "filter": {"expression": filter_expression},
        "limit": limit,
        "order": [{"key": {"name": "duration_nano"}, "direction": "desc"}],
        "disabled": False,
    }
    return builder_payload(window, [spec], request_type="raw")


def raw_logs_payload(filter_expression: str, window: TimeWindow, limit: int = 100) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": "A",
        "signal": "logs",
        "filter": {"expression": filter_expression},
        "limit": limit,
        "order": [{"key": {"name": "timestamp"}, "direction": "desc"}],
        "disabled": False,
    }
    return builder_payload(window, [spec], request_type="raw")


# ---------------------------------------------------------------- parsing


def series_values(envelope: dict[str, Any], query_name: str = "A") -> list[tuple[int, float]]:
    """Flatten a time_series result for one query into [(timestamp_ms, value)].

    Tolerates the v5 envelope (`data.data.results[].aggregations[].series[]`)
    plus missing/None aggregations (empty result)."""
    results = (envelope.get("data") or {}).get("data", {}).get("results") or []
    out: list[tuple[int, float]] = []
    for result in results:
        if result.get("queryName") != query_name:
            continue
        for agg in result.get("aggregations") or []:
            for series in agg.get("series") or []:
                for point in series.get("values") or []:
                    try:
                        out.append((int(point["timestamp"]), float(point["value"])))
                    except (KeyError, TypeError, ValueError):
                        continue
    return sorted(out)


def raw_rows(envelope: dict[str, Any], query_name: str = "A") -> list[dict[str, Any]]:
    """Flatten a raw-request result into a list of row dicts (`data` field of each row)."""
    results = (envelope.get("data") or {}).get("data", {}).get("results") or []
    out: list[dict[str, Any]] = []
    for result in results:
        if result.get("queryName") not in (query_name, None):
            continue
        for row in result.get("rows") or []:
            data = dict(row.get("data") or {})
            if "timestamp" in row and "timestamp" not in data:
                data["timestamp"] = row["timestamp"]
            out.append(data)
    return out


def mean(values: list[tuple[int, float]]) -> float:
    return sum(v for _, v in values) / len(values) if values else 0.0


def total(values: list[tuple[int, float]]) -> float:
    return sum(v for _, v in values)
