#!/usr/bin/env python3
"""Create the ARGUS spend meta-alert, idempotent:

An alert rule on the rate of ARGUS's own `argus.cost.usd` OTLP metric whose
webhook notification channel points back at ARGUS itself — the agent is
governed by the same alerting it consumes, and an overspending ARGUS pages
ARGUS about ARGUS.

Usage:  uv run python scripts/setup_meta_alert.py [--threshold USD_PER_HOUR]
        (use a tiny --threshold, e.g. 0.001, to make it fire for a demo)
Env:    SIGNOZ_URL (default http://localhost:8080), SIGNOZ_API_KEY (required)
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from dotenv import load_dotenv  # noqa: E402

from argus.signoz.rules import RuleClient, cost_meta_alert_rule  # noqa: E402

CHANNEL_NAME = "argus-webhook"  # created by scripts/setup_live.py


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=1.0,
                        help="USD per rolling hour (default 1.0)")
    args = parser.parse_args()

    load_dotenv()
    load_dotenv("../.env")
    base = os.getenv("SIGNOZ_URL", "http://localhost:8080").rstrip("/")
    key = os.getenv("SIGNOZ_API_KEY", "")
    if not key:
        sys.exit("SIGNOZ_API_KEY is not set (root .env)")

    client = RuleClient(base, key)
    rule = cost_meta_alert_rule([CHANNEL_NAME], threshold_usd_per_hour=args.threshold)
    existing = client.find_by_name(rule["alert"])
    if existing:
        print(f"rule '{rule['alert']}' already exists (id={existing.get('id')}) — "
              "delete it in the UI to recreate with a new threshold")
        return
    rule_id = client.create(rule)
    print(f"meta-alert created: id={rule_id} threshold=${args.threshold}/h")
    print(f"edit/inspect: {client.rule_url(rule_id)}")


if __name__ == "__main__":
    main()
