"""Dashboard factories + API client (act node, FR-12/13).

Uses the v1 dashboards API (`POST /api/v1/dashboards`) with the
dashboard-widget query dialect, which differs from the query_range dialect
(verified in research/signals-playbook.md §0/§4):
  - widget groupBy uses `key` + `dataType` + `type`  (NOT `name`/`fieldContext`)
  - widget `having` must be an array `[]`
  - list panels need selectColumns[].name + fieldContext + fieldDataType + signal
  - value panels must NOT have groupBy
"""

from __future__ import annotations

from typing import Any

import httpx


# ------------------------------------------------------------ building blocks


def _traces_query(
    name: str,
    aggregation: str,
    filter_expression: str,
    group_by: list[dict[str, str]] | None = None,
    legend: str = "",
) -> dict[str, Any]:
    return {
        "queryName": name,
        "dataSource": "traces",
        "expression": name,
        "disabled": False,
        "stepInterval": 60,
        "aggregations": [{"expression": aggregation}],
        "filter": {"expression": filter_expression},
        "groupBy": group_by or [],
        "having": [],
        "legend": legend,
        "orderBy": [],
        "reduceTo": "avg",
    }


def _builder_widget(
    widget_id: str,
    title: str,
    queries: list[dict[str, Any]],
    panel_type: str = "graph",
    y_axis_unit: str = "none",
    description: str = "",
) -> dict[str, Any]:
    return {
        "id": widget_id,
        "title": title,
        "description": description,
        "panelTypes": panel_type,
        "yAxisUnit": y_axis_unit,
        "softMax": None,
        "softMin": None,
        "isStacked": False,
        "nullZeroValues": "zero",
        "opacity": "1",
        "fillSpans": False,
        "query": {
            "queryType": "builder",
            "builder": {"queryData": queries, "queryFormulas": []},
            "promql": [], "clickhouse_sql": [],
        },
    }


def _layout(items: list[tuple[str, int, int, int, int]]) -> list[dict[str, Any]]:
    return [
        {"i": i, "x": x, "y": y, "w": w, "h": h, "minW": 3, "minH": 2,
         "static": False, "moved": False}
        for i, x, y, w, h in items
    ]


# ------------------------------------------------------------ dashboards


def incident_dashboard(service: str, investigation_id: str, alert_name: str) -> dict[str, Any]:
    """Per-incident evidence dashboard: the panels backing the RCA's claims,
    scoped to the offending service."""
    svc = f"service.name = '{service}'"
    widgets = [
        _builder_widget(
            "p99", f"p99 latency — {service}",
            [_traces_query("A", "p99(duration_nano)", svc, legend=service)],
            y_axis_unit="ns",
            description="The golden signal that fired. Compare against the alert boundary.",
        ),
        _builder_widget(
            "errors", f"Errored spans — {service}",
            [_traces_query("A", "count()", f"{svc} AND has_error = true", legend="errors")],
        ),
        _builder_widget(
            "throughput", f"Throughput — {service}",
            [_traces_query("A", "count()", svc, legend="spans/min")],
        ),
        _builder_widget(
            "by_operation", f"p95 by operation — {service}",
            [_traces_query(
                "A", "p95(duration_nano)", svc,
                group_by=[{"key": "name", "dataType": "string", "type": "tag"}],
                legend="{{name}}",
            )],
            y_axis_unit="ns",
            description="Which operation inside the service carries the latency.",
        ),
    ]
    return {
        "title": f"ARGUS incident {investigation_id} — {service}",
        "description": (
            f"Auto-created by ARGUS for alert '{alert_name}'. Every panel is one "
            f"of the queries the investigation ran; delete freely after review."
        ),
        "tags": ["argus", "incident", service],
        "layout": _layout([
            ("p99", 0, 0, 6, 6), ("errors", 6, 0, 6, 6),
            ("throughput", 0, 6, 6, 6), ("by_operation", 6, 6, 6, 6),
        ]),
        "variables": {},
        "widgets": widgets,
        "version": "v4",
    }


def mission_control_dashboard() -> dict[str, Any]:
    """ARGUS Mission Control: the agent's own gen_ai.* telemetry — the
    watcher, watched (FR-12)."""
    argus = "service.name = 'argus'"
    widgets = [
        _builder_widget(
            "investigations", "Investigations over time",
            [_traces_query("A", "count()", f"{argus} AND name = 'argus.investigation'",
                           legend="investigations")],
            description="One root span per alert investigated.",
        ),
        _builder_widget(
            "rca_latency", "Time to RCA (p95)",
            [_traces_query("A", "p95(duration_nano)",
                           f"{argus} AND name = 'argus.investigation'", legend="p95")],
            y_axis_unit="ns",
        ),
        _builder_widget(
            "tokens", "LLM token burn (output)",
            [_traces_query("A", "sum(gen_ai.usage.output_tokens)",
                           f"{argus} AND gen_ai.usage.output_tokens EXISTS",
                           group_by=[{"key": "gen_ai.request.model",
                                      "dataType": "string", "type": "tag"}],
                           legend="{{gen_ai.request.model}}")],
            description="gen_ai.usage.* attributes on ARGUS's own LLM spans.",
        ),
        _builder_widget(
            "cost", "Cost per investigation (USD)",
            [_traces_query("A", "sum(argus.cost.usd)",
                           f"{argus} AND name = 'argus.investigation'", legend="$ per run")],
        ),
        _builder_widget(
            "node_latency", "Investigation node latency (p95)",
            [_traces_query("A", "p95(duration_nano)",
                           f"{argus} AND name CONTAINS 'argus.node.'",
                           group_by=[{"key": "name", "dataType": "string", "type": "tag"}],
                           legend="{{name}}")],
            y_axis_unit="ns",
        ),
        _builder_widget(
            "signoz_reads", "SigNoz queries issued by ARGUS",
            [_traces_query("A", "count()",
                           f"{argus} AND name CONTAINS 'signoz.query_range'",
                           legend="queries")],
            description="Every read the agent performs, with rows/bytes scanned attributes.",
        ),
    ]
    return {
        "title": "ARGUS Mission Control",
        "description": "The agent that watches your services, watched by the same SigNoz — "
                       "gen_ai.* self-telemetry: investigations, RCA latency, token burn, cost.",
        "tags": ["argus", "gen_ai", "mission-control"],
        "layout": _layout([
            ("investigations", 0, 0, 6, 6), ("rca_latency", 6, 0, 6, 6),
            ("tokens", 0, 6, 6, 6), ("cost", 6, 6, 6, 6),
            ("node_latency", 0, 12, 6, 6), ("signoz_reads", 6, 12, 6, 6),
        ]),
        "variables": {},
        "widgets": widgets,
        "version": "v4",
    }


# ------------------------------------------------------------ API client


class DashboardClient:
    """Thin v1 dashboards API wrapper. `create` returns the dashboard URL."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, headers={"SIGNOZ-API-KEY": api_key})

    def find_by_title(self, title: str) -> str | None:
        resp = self._client.get(f"{self._base}/api/v1/dashboards")
        resp.raise_for_status()
        for d in resp.json().get("data") or []:
            data = d.get("data") or {}
            if data.get("title") == title:
                return str(d.get("id") or d.get("uuid") or "") or None
        return None

    def create(self, dashboard: dict[str, Any]) -> str:
        """Create (or return existing by title). Returns the dashboard URL."""
        existing = self.find_by_title(dashboard["title"])
        if existing:
            return f"{self._base}/dashboard/{existing}"
        resp = self._client.post(f"{self._base}/api/v1/dashboards", json=dashboard)
        resp.raise_for_status()
        body = resp.json().get("data") or {}
        dash_id = body.get("id") or body.get("uuid") or ""
        return f"{self._base}/dashboard/{dash_id}"
