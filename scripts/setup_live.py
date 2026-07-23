#!/usr/bin/env python3
"""Seed the live SigNoz instance for the ARGUS e2e demo (idempotent):

1. A webhook notification channel pointing at ARGUS's server
   (SigNoz runs in Docker, ARGUS on the host -> host.docker.internal).
2. A threshold alert rule on Faultline catalog p99 latency via the modern
   POST /api/v2/rules endpoint (verified in research/signals-playbook.md §3).

Usage:  uv run python scripts/setup_live.py
Env:    SIGNOZ_URL (default http://localhost:8080), SIGNOZ_API_KEY (required)
"""

from __future__ import annotations

import json
import os
import sys

import httpx
from dotenv import load_dotenv

CHANNEL_NAME = "argus-webhook"
RULE_NAME = "Faultline catalog p99 latency > 1s"
ARGUS_WEBHOOK_URL = os.getenv(
    "ARGUS_WEBHOOK_URL", "http://host.docker.internal:7331/webhook/signoz"
)


def client() -> tuple[httpx.Client, str]:
    load_dotenv()
    load_dotenv("../.env")
    base = os.getenv("SIGNOZ_URL", "http://localhost:8080").rstrip("/")
    key = os.getenv("SIGNOZ_API_KEY", "")
    if not key:
        sys.exit("SIGNOZ_API_KEY is not set (root .env)")
    return httpx.Client(
        base_url=base, headers={"SIGNOZ-API-KEY": key}, timeout=30
    ), base


def ensure_channel(c: httpx.Client) -> None:
    existing = c.get("/api/v1/channels").json().get("data") or []
    if any(ch.get("name") == CHANNEL_NAME for ch in existing):
        print(f"channel '{CHANNEL_NAME}' already exists")
        return
    resp = c.post(
        "/api/v1/channels",
        json={
            "name": CHANNEL_NAME,
            "webhook_configs": [{
                "send_resolved": True,
                "url": ARGUS_WEBHOOK_URL,
            }],
        },
    )
    print(f"create channel -> HTTP {resp.status_code}: {resp.text[:200]}")
    resp.raise_for_status()


RULE = {
    "alert": RULE_NAME,
    "alertType": "TRACES_BASED_ALERT",
    "ruleType": "threshold_rule",
    "version": "v5",
    "schemaVersion": "v2alpha1",
    "condition": {
        "compositeQuery": {
            "queryType": "builder",
            "panelType": "graph",
            "unit": "ns",
            "queries": [{
                "type": "builder_query",
                "spec": {
                    "name": "A",
                    "signal": "traces",
                    "stepInterval": 60,
                    "aggregations": [{"expression": "p99(duration_nano)"}],
                    "filter": {"expression": "service.name = 'catalog'"},
                    "groupBy": [{
                        "name": "service.name",
                        "fieldContext": "resource",
                        "fieldDataType": "string",
                    }],
                    "legend": "{{service.name}}",
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
                "target": 1,
                "targetUnit": "s",
                "channels": [CHANNEL_NAME],
            }],
        },
    },
    "evaluation": {"kind": "rolling", "spec": {"evalWindow": "5m", "frequency": "1m"}},
    "notificationSettings": {
        "groupBy": ["service.name"],
        "renotify": {"enabled": True, "interval": "10m", "alertStates": ["firing"]},
    },
    "labels": {"severity": "critical", "team": "faultline", "owner": "argus-demo"},
    "annotations": {
        "summary": "catalog latency degraded",
        "description": "p99 latency for {{$labels.service.name}} crossed 1s "
                       "(threshold {{$threshold}}).",
    },
}


def ensure_rule(c: httpx.Client) -> None:
    existing = c.get("/api/v2/rules").json().get("data") or []
    rules = existing.get("rules", existing) if isinstance(existing, dict) else existing
    for r in rules or []:
        if (r.get("alert") or r.get("data", {}).get("alert")) == RULE_NAME:
            print(f"rule '{RULE_NAME}' already exists (id={r.get('id')})")
            return
    resp = c.post("/api/v2/rules", json=RULE)
    print(f"create rule -> HTTP {resp.status_code}: {resp.text[:300]}")
    resp.raise_for_status()


def main() -> None:
    c, base = client()
    ensure_channel(c)
    ensure_rule(c)
    print(f"done. Alerts page: {base}/alerts")


if __name__ == "__main__":
    main()
