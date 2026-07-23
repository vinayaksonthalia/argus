import pytest

from argus.models import dedup_fingerprint
from argus.nodes.triage import LOOKBACK_MINUTES, TriageError, parse_webhook, triage


def test_parse_webhook_envelope(alert_payload):
    alert = parse_webhook(alert_payload)
    assert alert.name == "CatalogP99LatencyAnomaly"
    assert alert.service == "catalog"
    assert alert.status == "firing"
    assert alert.starts_at is not None
    assert alert.starts_at.year == 2026


def test_parse_webhook_bare_alert():
    alert = parse_webhook({"labels": {"alertname": "X", "service_name": "svc"}})
    assert alert.name == "X"
    assert alert.service == "svc"


@pytest.mark.parametrize("payload", [
    {},
    {"alerts": []},
    {"foo": "bar"},
    {"alerts": [{"labels": "not-a-dict"}]},
    {"alerts": [{"labels": {}, "startsAt": "not-a-timestamp"}]},
])
def test_parse_webhook_malformed_raises(payload):
    with pytest.raises(TriageError):
        parse_webhook(payload)


def test_triage_sets_service_window_fingerprint(state):
    state.service = "unknown"
    state.window = None
    out = triage(state)
    assert out.service == "catalog"
    assert out.window is not None
    assert (out.window.end - out.window.start).total_seconds() >= LOOKBACK_MINUTES * 60
    assert len(out.fingerprint) == 16


def test_dedup_fingerprint_stable_within_bucket(alert, window):
    fp1 = dedup_fingerprint(alert, window)
    fp2 = dedup_fingerprint(alert, window)
    assert fp1 == fp2


def test_dedup_fingerprint_differs_across_alerts(alert, window):
    other = alert.model_copy(update={"labels": {**alert.labels, "alertname": "Other"}})
    assert dedup_fingerprint(alert, window) != dedup_fingerprint(other, window)
