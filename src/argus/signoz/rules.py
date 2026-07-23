"""Alert-rule factories + API client (act node FR-15, meta-alert row 9).

Uses the modern rules API (`/api/v2/rules`, schemaVersion v2alpha1 — verified
in research/signals-playbook.md §3). Safety stance: every rule ARGUS creates
from an investigation is a **DRAFT** — `disabled: true` and clearly named
`[DRAFT · ARGUS]` — a human enables it after review. ARGUS never mutates or
deletes existing rules.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

DRAFT_PREFIX = "[DRAFT · ARGUS] "


def _threshold_rule(
    name: str,
    signal: str,
    aggregation: str,
    filter_expression: str,
    target: float,
    target_unit: str,
    op: str,
    description: str,
    channels: list[str],
    disabled: bool,
    labels: Optional[dict[str, str]] = None,
    eval_window: str = "5m",
    y_unit: str = "",
) -> dict[str, Any]:
    alert_type = {
        "traces": "TRACES_BASED_ALERT",
        "logs": "LOGS_BASED_ALERT",
        "metrics": "METRIC_BASED_ALERT",
    }[signal]
    composite: dict[str, Any] = {
        "queryType": "builder",
        "panelType": "graph",
        "queries": [{
            "type": "builder_query",
            "spec": {
                "name": "A",
                "signal": signal,
                "stepInterval": 60,
                "aggregations": [{"expression": aggregation}],
                "filter": {"expression": filter_expression},
                "legend": name,
            },
        }],
    }
    if y_unit:
        composite["unit"] = y_unit
    return {
        "alert": name,
        "alertType": alert_type,
        "ruleType": "threshold_rule",
        "version": "v5",
        "schemaVersion": "v2alpha1",
        "disabled": disabled,
        "condition": {
            "compositeQuery": composite,
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [{
                    "name": "critical",
                    "op": op,
                    "matchType": "at_least_once",
                    "target": target,
                    **({"targetUnit": target_unit} if target_unit else {}),
                    "channels": channels,
                }],
            },
        },
        "evaluation": {
            "kind": "rolling",
            "spec": {"evalWindow": eval_window, "frequency": "1m"},
        },
        # required by the v2alpha1 schema (validation fails without it)
        "notificationSettings": {
            "groupBy": [],
            "renotify": {"enabled": False},
        },
        "labels": {"owner": "argus", **(labels or {})},
        "annotations": {
            "summary": name,
            "description": description,
        },
    }


def draft_rule_from_hypothesis(
    service: str,
    investigation_id: str,
    alert_name: str,
    claim: str,
    spec_params: dict[str, Any],
    channels: list[str],
) -> Optional[dict[str, Any]]:
    """Turn a CONFIRMED hypothesis's verification spec into a DRAFT follow-up
    alert rule — the leading indicator for this failure class. Returns None
    when the spec doesn't map onto a threshold rule (e.g. before/after
    ratios, which have no rolling-window equivalent)."""
    signal = str(spec_params.get("signal", "traces"))
    if signal not in ("traces", "logs"):
        return None
    filter_expression = str(spec_params.get("filter_expression", "")).strip()
    if not filter_expression:
        return None
    aggregation = str(spec_params.get("aggregation", "count()")).strip() or "count()"
    op = str(spec_params.get("op", ""))
    expected_value = spec_params.get("expected_value")

    if op == "contains":
        # "this message/attribute appears" -> alert when matching rows exist.
        needle = str(expected_value or "").replace("'", "")
        column = "body" if signal == "logs" else "name"
        if needle:
            filter_expression = f"{filter_expression} AND {column} CONTAINS '{needle}'"
        aggregation, target, rule_op = "count()", 0.0, "above"
    elif op in ("gt", "ratio_gt"):
        # gt: alert above the confirmed level. ratio_gt has no direct rolling
        # equivalent; fall back to counting matching spans/logs above zero
        # for count() aggregations, else skip.
        if op == "ratio_gt" and not aggregation.startswith("count"):
            return None
        try:
            target = float(expected_value) if op == "gt" else 0.0
        except (TypeError, ValueError):
            return None
        rule_op = "above"
    elif op == "lt":
        try:
            target = float(expected_value)
        except (TypeError, ValueError):
            return None
        rule_op = "below"
    else:
        return None

    name = f"{DRAFT_PREFIX}{service}: {claim[:80]}"
    description = (
        f"Draft leading-indicator rule auto-proposed by ARGUS investigation "
        f"{investigation_id} (alert '{alert_name}'). Root-cause claim: {claim} "
        f"— review the threshold and ENABLE manually. ARGUS never enables "
        f"rules on its own."
    )
    return _threshold_rule(
        name=name,
        signal=signal,
        aggregation=aggregation,
        filter_expression=filter_expression,
        target=target,
        target_unit="",
        op=rule_op,
        description=description,
        channels=channels,
        disabled=True,  # DRAFT: never auto-enabled (safety invariant)
        labels={"severity": "warning", "argus.draft": "true",
                "argus.investigation_id": investigation_id},
    )


def cost_meta_alert_rule(
    channels: list[str],
    threshold_usd_per_hour: float = 1.0,
    metric_name: str = "argus.cost.usd",
) -> dict[str, Any]:
    """The meta-alert: alert on ARGUS's own LLM spend rate.
    Its webhook channel points back at ARGUS — the agent is governed by the
    same alerting it consumes, and an overspending ARGUS pages ARGUS."""
    return {
        "alert": "ARGUS LLM spend rate",
        "alertType": "METRIC_BASED_ALERT",
        "ruleType": "threshold_rule",
        "version": "v5",
        "schemaVersion": "v2alpha1",
        "condition": {
            "compositeQuery": {
                "queryType": "builder",
                "panelType": "graph",
                "queries": [{
                    "type": "builder_query",
                    "spec": {
                        "name": "A",
                        "signal": "metrics",
                        "stepInterval": 60,
                        # max-per-series then sum: each ARGUS process exports a
                        # cumulative USD counter, so sum-of-max over the rolling
                        # window = spend in that window across processes.
                        # ("increase" reads 0 for short-lived processes whose
                        # counter arrives in a single sample — verified live.)
                        "aggregations": [{
                            "metricName": metric_name,
                            "timeAggregation": "max",
                            "spaceAggregation": "sum",
                        }],
                        "legend": "ARGUS $ spend",
                    },
                }],
            },
            "selectedQueryName": "A",
            "thresholds": {
                "kind": "basic",
                "spec": [{
                    "name": "critical",
                    "op": "above",
                    "matchType": "at_least_once",
                    "target": threshold_usd_per_hour,
                    "channels": channels,
                }],
            },
        },
        "evaluation": {"kind": "rolling", "spec": {"evalWindow": "1h", "frequency": "1m"}},
        "notificationSettings": {
            "groupBy": [],
            "renotify": {"enabled": True, "interval": "30m", "alertStates": ["firing"]},
        },
        "labels": {"severity": "warning", "owner": "argus", "service": "argus",
                   "meta": "argus-pages-itself"},
        "annotations": {
            "summary": "ARGUS LLM spend is above budget",
            "description": (
                "The argus.cost.usd metric (emitted by ARGUS per investigation) "
                "crossed the hourly budget. This alert's webhook points back at "
                "ARGUS: the agent investigates its own spend."
            ),
        },
    }


class RuleClient:
    """Thin /api/v2/rules wrapper: create + list + get. Never deletes."""

    def __init__(self, base_url: str, api_key: str, timeout: float = 30.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout, headers={"SIGNOZ-API-KEY": api_key})

    def list(self) -> list[dict[str, Any]]:
        resp = self._client.get(f"{self._base}/api/v2/rules")
        resp.raise_for_status()
        data = resp.json().get("data") or []
        return data.get("rules", data) if isinstance(data, dict) else data

    def find_by_name(self, name: str) -> Optional[dict[str, Any]]:
        for r in self.list():
            if (r.get("alert") or (r.get("data") or {}).get("alert")) == name:
                return r
        return None

    def create(self, rule: dict[str, Any]) -> str:
        """Create (idempotent by rule name). Returns the rule id."""
        existing = self.find_by_name(rule["alert"])
        if existing:
            return str(existing.get("id", ""))
        resp = self._client.post(f"{self._base}/api/v2/rules", json=rule)
        resp.raise_for_status()
        body = resp.json().get("data") or {}
        if isinstance(body, dict):
            return str(body.get("id", ""))
        return str(body)

    def rule_url(self, rule_id: str) -> str:
        return f"{self._base}/alerts/edit?ruleId={rule_id}"
