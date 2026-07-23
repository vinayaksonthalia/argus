"""Triage node: parse the Alertmanager-compatible webhook payload into a
service, an investigation window, and a dedup fingerprint (FR-1/FR-2)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from ..models import Alert, InvestigationState, TimeWindow, dedup_fingerprint

LOOKBACK_MINUTES = 30


class TriageError(ValueError):
    """Raised for malformed webhook payloads (server maps this to 4xx)."""


def parse_webhook(payload: dict[str, Any]) -> Alert:
    """Accepts Alertmanager-style payloads: either the envelope with `alerts: []`
    or a single bare alert object."""
    if not isinstance(payload, dict):
        raise TriageError("webhook payload must be a JSON object")
    alerts = payload.get("alerts")
    if isinstance(alerts, list) and alerts:
        raw = alerts[0]
    elif "labels" in payload or "annotations" in payload:
        raw = payload
    else:
        raise TriageError("payload has no 'alerts' array and no 'labels' — not an alert")
    if not isinstance(raw, dict) or not isinstance(raw.get("labels", {}), dict):
        raise TriageError("alert item malformed: 'labels' must be an object")

    starts_at = None
    raw_ts = raw.get("startsAt") or raw.get("starts_at")
    if raw_ts:
        try:
            starts_at = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
        except ValueError as exc:
            raise TriageError(f"invalid startsAt timestamp: {raw_ts!r}") from exc

    return Alert(
        status=str(raw.get("status", payload.get("status", "firing"))),
        labels={str(k): str(v) for k, v in raw.get("labels", {}).items()},
        annotations={str(k): str(v) for k, v in raw.get("annotations", {}).items()},
        starts_at=starts_at,
        fingerprint=raw.get("fingerprint"),
    )


def triage(state: InvestigationState) -> InvestigationState:
    alert = state.alert
    state.service = alert.service or "unknown"

    end = datetime.now(timezone.utc)
    start_anchor = alert.starts_at or end
    if start_anchor.tzinfo is None:
        start_anchor = start_anchor.replace(tzinfo=timezone.utc)
    state.window = TimeWindow(
        start=start_anchor - timedelta(minutes=LOOKBACK_MINUTES), end=end
    )
    state.fingerprint = dedup_fingerprint(alert, state.window)
    return state


def make(_deps: object = None):
    return triage
