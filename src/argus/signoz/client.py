"""High-level SigNoz client used by graph nodes.

Wraps a `SignozTransport` (live or replay) with domain operations: golden
signals with before/after comparison, exemplar trace retrieval, correlated
log search, and mechanical execution of hypothesis verification specs.
"""

from __future__ import annotations

from typing import Any

from ..models import Expected, SpanInfo, TimeWindow, VerificationKind, VerificationSpec
from ..security import scrub_attributes
from . import queries as q
from .transport import SignozTransport


class SignozClient:
    def __init__(self, transport: SignozTransport) -> None:
        self._t = transport

    @property
    def stats(self):
        """Query-cost accumulator (meta.rowsScanned et al) from the transport."""
        return getattr(self._t, "stats", None)

    # ------------------------------------------------------------ golden signals

    def golden_signals(self, service: str, window: TimeWindow) -> dict[str, dict[str, float]]:
        """p99 latency / error rate / throughput, each measured over the alert
        window and the preceding hour. Returns {signal: {before, after, ratio}}."""
        before = window.before_window(60)
        out: dict[str, dict[str, float]] = {}

        for label, win in (("before", before), ("after", window)):
            env = self._t.query_range(q.p99_latency_payload(service, win), f"golden.p99.{label}")
            out.setdefault("p99_latency_ms", {})[label] = q.mean(q.series_values(env)) / 1e6

            env = self._t.query_range(q.error_rate_payload(service, win), f"golden.error_rate.{label}")
            errored = q.total(q.series_values(env, "A"))
            total_spans = q.total(q.series_values(env, "B"))
            out.setdefault("error_rate", {})[label] = (
                errored / total_spans if total_spans else 0.0
            )

            env = self._t.query_range(q.throughput_payload(service, win), f"golden.throughput.{label}")
            duration_min = max((win.end_ms - win.start_ms) / 60000, 1)
            out.setdefault("throughput_per_min", {})[label] = q.total(q.series_values(env)) / duration_min

        for signal, vals in out.items():
            b, a = vals.get("before", 0.0), vals.get("after", 0.0)
            vals["ratio"] = (a / b) if b else (float("inf") if a else 1.0)
        return out

    # ------------------------------------------------------------ traces

    def search_error_traces(
        self, service: str, window: TimeWindow, limit: int = 3, tag: str = "traces.search"
    ) -> list[dict[str, Any]]:
        expr = f"service.name = '{service}' AND has_error = true"
        env = self._t.query_range(q.raw_traces_payload(expr, window, limit=limit), tag)
        return q.raw_rows(env)

    def search_slow_traces(
        self, service: str, window: TimeWindow, limit: int = 3, tag: str = "traces.search.slow"
    ) -> list[dict[str, Any]]:
        """Latency-incident fallback: slowest spans for the service (the raw
        payload already orders by duration_nano desc)."""
        env = self._t.query_range(
            q.raw_traces_payload(f"service.name = '{service}'", window, limit=limit), tag
        )
        return q.raw_rows(env)

    def trace_spans(self, trace_id: str, window: TimeWindow, tag: str) -> list[SpanInfo]:
        env = self._t.query_range(
            q.raw_traces_payload(f"trace_id = '{trace_id}'", window, limit=200), tag
        )
        spans: list[SpanInfo] = []
        for row in q.raw_rows(env):
            attrs = {
                k: str(v)
                for k, v in row.items()
                if k not in ("timestamp",) and isinstance(v, (str, int, float, bool))
            }
            # Live v5 raw rows nest span attributes and resource attributes as
            # dicts ('attributes', 'resource'); flatten them so db.statement,
            # service.name etc. are reachable (fixtures may already be flat).
            for nested_key in ("attributes", "resource"):
                nested = row.get(nested_key)
                if isinstance(nested, dict):
                    attrs.update({k: str(v) for k, v in nested.items()})
            spans.append(
                SpanInfo(
                    span_id=str(row.get("span_id", "")),
                    parent_span_id=str(row.get("parent_span_id",
                                                attrs.get("parent_span_id", ""))),
                    trace_id=str(row.get("trace_id", trace_id)),
                    name=str(row.get("name", "")),
                    service=str(attrs.get("service.name", attrs.get("service_name", ""))),
                    duration_ms=float(row.get("duration_nano", 0)) / 1e6,
                    has_error=bool(row.get("has_error", False)),
                    attributes=scrub_attributes(attrs),
                    events=[str(e) for e in row.get("events", [])] if isinstance(row.get("events"), list) else [],
                )
            )
        return spans

    # ------------------------------------------------------------ logs

    def search_logs(
        self, filter_expression: str, window: TimeWindow, tag: str, limit: int = 100
    ) -> list[dict[str, Any]]:
        env = self._t.query_range(q.raw_logs_payload(filter_expression, window, limit=limit), tag)
        rows = q.raw_rows(env)
        # Live v5 log rows nest attributes in 'attributes_string'/'resources_string'
        # (and sometimes 'attributes'/'resource'); flatten so nodes can read
        # keys like service.name and event.name directly.
        for row in rows:
            for nested_key in ("attributes_string", "resources_string", "attributes", "resource"):
                nested = row.get(nested_key)
                if isinstance(nested, dict):
                    for k, v in nested.items():
                        row.setdefault(k, v)
        return rows

    # ------------------------------------------------------------ verification

    def run_verification(
        self, spec: VerificationSpec, window: TimeWindow, tag: str
    ) -> tuple[bool, str]:
        """Execute one falsifiable verification spec (FR-7). Params are
        whitelisted; the result is (passed, detail)."""
        expected = spec.expected
        params = spec.params
        filter_expression = str(params.get("filter_expression", ""))
        aggregation = str(params.get("aggregation", "count()"))
        signal = str(params.get("signal", "traces"))
        q.validate_verification_params(signal, aggregation, filter_expression)

        if spec.kind == VerificationKind.query_range:
            return self._verify_query_range(
                signal, aggregation, filter_expression, expected, window, tag
            )
        if spec.kind == VerificationKind.trace_check:
            env = self._t.query_range(q.raw_traces_payload(filter_expression, window, 20), tag)
            return self._verify_rows(q.raw_rows(env), expected)
        if spec.kind == VerificationKind.log_check:
            env = self._t.query_range(q.raw_logs_payload(filter_expression, window, 100), tag)
            return self._verify_rows(q.raw_rows(env), expected)
        return False, f"unknown verification kind {spec.kind}"

    def _verify_query_range(
        self,
        signal: str,
        aggregation: str,
        filter_expression: str,
        expected: Expected,
        window: TimeWindow,
        tag: str,
    ) -> tuple[bool, str]:
        def measure(win: TimeWindow, sub: str) -> float:
            spec = {
                "name": "A",
                "signal": signal,
                "aggregations": [{"expression": aggregation}],
                "stepInterval": 60,
                "disabled": False,
            }
            if filter_expression:
                spec["filter"] = {"expression": filter_expression}
            env = self._t.query_range(q.builder_payload(win, [spec]), f"{tag}.{sub}")
            values = q.series_values(env)
            return q.total(values) if aggregation.startswith("count") else q.mean(values)

        if expected.op == "ratio_gt":
            before = measure(window.before_window(60), "before")
            after = measure(window, "after")
            ratio = after / before if before else (float("inf") if after else 0.0)
            passed = ratio > float(expected.value)
            return passed, f"{aggregation} after/before ratio = {ratio:.2f} (need > {expected.value})"
        measured = measure(window, "after")
        if expected.op == "gt":
            return measured > float(expected.value), f"{aggregation} = {measured:.2f} (need > {expected.value})"
        if expected.op == "lt":
            return measured < float(expected.value), f"{aggregation} = {measured:.2f} (need < {expected.value})"
        return False, f"op '{expected.op}' not valid for query_range"

    @staticmethod
    def _verify_rows(rows: list[dict[str, Any]], expected: Expected) -> tuple[bool, str]:
        if expected.op == "contains":
            needle = str(expected.value).lower()
            for row in rows:
                blob = " ".join(str(v) for v in row.values()).lower()
                if needle in blob:
                    return True, f"found '{expected.value}' in {len(rows)} matching rows"
            return False, f"'{expected.value}' not found in {len(rows)} rows"
        if expected.op == "gt":
            return len(rows) > float(expected.value), f"{len(rows)} rows (need > {expected.value})"
        if expected.op == "lt":
            return len(rows) < float(expected.value), f"{len(rows)} rows (need < {expected.value})"
        return False, f"op '{expected.op}' not valid for row checks"
