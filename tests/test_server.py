"""Webhook server: parsing, dedup/idempotency, malformed -> 4xx."""

from unittest.mock import patch

from fastapi.testclient import TestClient

from argus.config import Settings
from argus.server import create_app


def make_client() -> TestClient:
    app = create_app(Settings())
    return TestClient(app)


def test_healthz():
    assert make_client().get("/healthz").json() == {"status": "ok"}


def test_malformed_payload_400():
    client = make_client()
    resp = client.post("/webhook/signoz", json={"nope": True})
    assert resp.status_code == 400


def test_webhook_accepts_and_dedups(alert_payload):
    client = make_client()
    # Patch the background investigation so no live SigNoz/LLM is touched.
    with patch("argus.investigation.run_investigation") as run:
        run.return_value = None
        r1 = client.post("/webhook/signoz", json=alert_payload)
        assert r1.status_code == 202
        body1 = r1.json()
        assert body1["deduplicated"] is False

        r2 = client.post("/webhook/signoz", json=alert_payload)
        body2 = r2.json()
        assert body2["deduplicated"] is True
        assert body2["investigation_id"] == body1["investigation_id"]


def test_investigations_listing(alert_payload):
    client = make_client()
    with patch("argus.investigation.run_investigation") as run:
        run.return_value = None
        client.post("/webhook/signoz", json=alert_payload)
    listing = client.get("/investigations").json()["investigations"]
    assert len(listing) == 1


def test_resolved_alert_is_skipped():
    client = make_client()
    payload = {
        "status": "resolved",
        "alerts": [{
            "status": "resolved",
            "labels": {"alertname": "X", "service.name": "catalog"},
            "startsAt": "2026-07-16T12:00:00Z",
        }],
    }
    resp = client.post("/webhook/signoz", json=payload)
    assert resp.status_code == 202
    assert resp.json()["skipped"]
