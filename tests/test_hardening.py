"""Hardening fixes: webhook auth, dedup persistence across restarts,
SigNoz retry-with-backoff, and error-verdict separation in reports."""

from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from argus.config import ConfigError, Settings
from argus.models import Hypothesis, Verdict
from argus.server import DedupStore, create_app
from argus.signoz.transport import HttpTransport


# ---------------------------------------------------------------- webhook auth

SECRET = "s3cret-webhook-value"


def make_auth_client() -> TestClient:
    app = create_app(Settings(state_db="off", webhook_secret=SECRET))
    return TestClient(app)


def test_webhook_rejects_missing_secret(alert_payload):
    resp = make_auth_client().post("/webhook/signoz", json=alert_payload)
    assert resp.status_code == 401


def test_webhook_non_ascii_secret_is_401_not_500(alert_payload):
    # compare_digest(str, str) raises TypeError on non-ASCII; must be a clean 401
    resp = make_auth_client().post(
        "/webhook/signoz", json=alert_payload,
        # raw latin-1 header bytes, as a hostile client would send them
        headers={"X-Argus-Webhook-Secret": "s\xe9cret-\xfcnicode".encode("latin-1")},
    )
    assert resp.status_code == 401


def test_webhook_rejects_wrong_secret(alert_payload):
    resp = make_auth_client().post(
        "/webhook/signoz", json=alert_payload,
        headers={"X-Argus-Webhook-Secret": "wrong"},
    )
    assert resp.status_code == 401


def test_webhook_accepts_header_secret(alert_payload):
    client = make_auth_client()
    with patch("argus.investigation.run_investigation", return_value=None):
        resp = client.post(
            "/webhook/signoz", json=alert_payload,
            headers={"X-Argus-Webhook-Secret": SECRET},
        )
    assert resp.status_code == 202


def test_webhook_accepts_bearer_secret(alert_payload):
    client = make_auth_client()
    with patch("argus.investigation.run_investigation", return_value=None):
        resp = client.post(
            "/webhook/signoz", json=alert_payload,
            headers={"Authorization": f"Bearer {SECRET}"},
        )
    assert resp.status_code == 202


def test_healthz_needs_no_secret():
    assert make_auth_client().get("/healthz").status_code == 200


def test_no_secret_stays_open(alert_payload):
    """Backward compatible: without a configured secret the webhook accepts
    unauthenticated posts (with a startup warning)."""
    app = create_app(Settings(state_db="off"))
    with patch("argus.investigation.run_investigation", return_value=None):
        resp = TestClient(app).post("/webhook/signoz", json=alert_payload)
    assert resp.status_code == 202


def test_placeholder_webhook_secret_refused():
    with pytest.raises(ConfigError):
        Settings(
            signoz_api_key="real-key-value", webhook_secret="changeme"
        ).validate_live()


# ------------------------------------------------------- dedup persistence

def test_dedup_survives_restart(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = DedupStore(db)
    assert store.claim("fp-1", "catalog", "inv-a") is None
    store.finish("inv-a", "catalog", {"status": "done"})

    reborn = DedupStore(db)  # simulated restart
    assert reborn.claim("fp-1", "catalog", "inv-b") == "inv-a"
    assert reborn.results["inv-a"]["status"] == "done"


def test_running_marked_interrupted_after_restart(tmp_path):
    db = tmp_path / "state.sqlite3"
    store = DedupStore(db)
    store.claim("fp-1", "catalog", "inv-a")  # never finishes (crash)

    reborn = DedupStore(db)
    assert reborn.results["inv-a"]["status"] == "interrupted"
    # the service must not be considered active anymore: a new, different
    # alert for it gets a fresh investigation
    assert reborn.claim("fp-2", "catalog", "inv-b") is None


def test_memory_only_store_still_works():
    store = DedupStore(None)
    assert store.claim("fp", "svc", "inv-1") is None
    assert store.claim("fp", "svc", "inv-2") == "inv-1"


# ------------------------------------------------------------ transport retry

class _FlakySigNoz:
    """Stand-in for httpx.Client: fails N times, then succeeds."""

    def __init__(self, failures: list):
        self._failures = failures
        self.calls = 0

    def post(self, url, json=None):
        self.calls += 1
        if self._failures:
            item = self._failures.pop(0)
            if isinstance(item, Exception):
                raise item
            return httpx.Response(
                item, request=httpx.Request("POST", url), json={}
            )
        return httpx.Response(
            200, request=httpx.Request("POST", url),
            json={"status": "success", "data": {"meta": {}, "data": {"results": []}}},
        )


def _no_sleep_transport(failures):
    t = HttpTransport("http://signoz", "key")
    t._client = _FlakySigNoz(failures)
    return t


def test_retry_recovers_from_connect_error(monkeypatch):
    monkeypatch.setattr("argus.signoz.transport.time.sleep", lambda s: None)
    t = _no_sleep_transport([httpx.ConnectError("boom")])
    envelope = t.query_range({"q": 1}, "golden.test")
    assert envelope["status"] == "success"
    assert t._client.calls == 2


def test_retry_recovers_from_503(monkeypatch):
    monkeypatch.setattr("argus.signoz.transport.time.sleep", lambda s: None)
    t = _no_sleep_transport([503])
    assert t.query_range({"q": 1}, "golden.test")["status"] == "success"
    assert t._client.calls == 2


def test_retry_gives_up_after_max_attempts(monkeypatch):
    monkeypatch.setattr("argus.signoz.transport.time.sleep", lambda s: None)
    t = _no_sleep_transport([httpx.ConnectError("a"), httpx.ConnectError("b"),
                             httpx.ConnectError("c")])
    with pytest.raises(httpx.ConnectError):
        t.query_range({"q": 1}, "golden.test")
    assert t._client.calls == 3


def test_4xx_is_not_retried(monkeypatch):
    monkeypatch.setattr("argus.signoz.transport.time.sleep", lambda s: None)
    t = _no_sleep_transport([400])
    with pytest.raises(httpx.HTTPStatusError):
        t.query_range({"q": 1}, "golden.test")
    assert t._client.calls == 1


# ------------------------------------------- error verdict != refuted in report

def _hypothesis(claim: str, verdict: Verdict) -> Hypothesis:
    h = Hypothesis(
        claim=claim, mechanism="m", confidence=0.7,
        verification={
            "kind": "log_check", "params": {},
            "expected": {"op": "contains", "value": "x"},
        },
    )
    h.verdict = verdict
    h.verdict_detail = "detail"
    return h


def test_report_separates_unverified_from_refuted(state, deps):
    from argus.nodes.report import make

    state.hypotheses = [
        _hypothesis("truly refuted", Verdict.refuted),
        _hypothesis("spec crashed", Verdict.error),
    ]
    state = make(deps)(state)
    rpt = state.report
    assert rpt.refuted == ["truly refuted — detail"]
    assert rpt.unverified == ["spec crashed — detail"]
    assert "UNVERIFIED — check failed to run" in rpt.postmortem_md
    # the untested theory must not be rendered as "ruled out" in Slack
    ruled_out = [b for b in rpt.slack_blocks
                 if "Ruled out" in str(b.get("text", {}).get("text", ""))]
    assert all("spec crashed" not in str(b) for b in ruled_out)


# ------------------------------------------------- adaptive review threshold

def _memory_evidence(similarity: float, confidence: float, degraded: bool):
    from argus.models import Evidence, EvidenceKind

    return Evidence(
        kind=EvidenceKind.memory, source="memory.recall",
        summary=f"similar to incident inv-past (similarity {similarity:.0%})",
        data={
            "incident_id": "inv-past", "similarity": similarity,
            "confidence": confidence, "degraded": degraded,
        },
    )


def _run_report(state, deps, hypothesis_confidence: float, memory=None):
    from argus.nodes.report import make

    h = _hypothesis("plausible cause", Verdict.confirmed)
    h.confidence = hypothesis_confidence
    state.hypotheses = [h]
    if memory is not None:
        state.add_evidence(memory)
    return make(deps)(state).report


def test_verified_memory_match_lowers_the_bar(state, deps):
    rpt = _run_report(state, deps, 0.68,
                      _memory_evidence(0.80, confidence=0.90, degraded=False))
    assert rpt.review_threshold == pytest.approx(0.65)
    assert rpt.needs_review is False
    assert "known failure class" in rpt.threshold_note


def test_degraded_memory_earns_no_discount(state, deps):
    rpt = _run_report(state, deps, 0.68,
                      _memory_evidence(0.80, confidence=0.90, degraded=True))
    assert rpt.review_threshold == pytest.approx(0.75)
    assert rpt.needs_review is True
    assert rpt.threshold_note == ""


def test_unverified_memory_earns_no_discount(state, deps):
    # past incident concluded below the bar -> proves nothing
    rpt = _run_report(state, deps, 0.68,
                      _memory_evidence(0.80, confidence=0.60, degraded=False))
    assert rpt.review_threshold == pytest.approx(0.75)
    assert rpt.needs_review is True


def test_low_similarity_memory_earns_no_discount(state, deps):
    # below CITE_SIMILARITY (0.55) the match is context, not a citation
    rpt = _run_report(state, deps, 0.68,
                      _memory_evidence(0.40, confidence=0.90, degraded=False))
    assert rpt.review_threshold == pytest.approx(0.75)
    assert rpt.needs_review is True


def test_discount_cannot_rescue_a_weak_run(state, deps):
    rpt = _run_report(state, deps, 0.55,
                      _memory_evidence(0.80, confidence=0.90, degraded=False))
    assert rpt.needs_review is True  # 0.55 < 0.65 even with the discount


def test_no_memory_keeps_default_bar(state, deps):
    rpt = _run_report(state, deps, 0.68)
    assert rpt.review_threshold == pytest.approx(0.75)
    assert rpt.needs_review is True
    # the postmortem states the bar it judged against
    assert "**Review bar:** 75%" in rpt.postmortem_md


def test_degraded_run_never_gets_discount(state, deps):
    from argus.nodes.report import make

    state.hypotheses = [_hypothesis("dead theory", Verdict.refuted)]
    state.add_evidence(_memory_evidence(0.80, confidence=0.90, degraded=False))
    rpt = make(deps)(state).report
    assert rpt.degraded is True
    assert rpt.needs_review is True
    assert rpt.review_threshold == pytest.approx(0.75)
