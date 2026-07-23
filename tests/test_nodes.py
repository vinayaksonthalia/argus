"""Per-node tests over the recorded incident-1 fixture (no network, no LLM)."""

import pytest

from argus.models import EvidenceKind, Verdict
from argus.nodes import change_corr, golden_signals, hypothesize, infra, log_corr, trace_dive, verify


def test_golden_signals_before_after(state, deps):
    out = golden_signals.make(deps)(state)
    metric_evs = {e.source: e for e in out.evidence if e.kind == EvidenceKind.metric}
    p99 = metric_evs["golden_signals.p99_latency_ms"]
    assert p99.data["ratio"] > 10  # 120ms -> ~1.8s mean
    err = metric_evs["golden_signals.error_rate"]
    assert err.data["before"] < 0.01 and err.data["after"] > 0.1
    assert all(e.links for e in metric_evs.values())


def test_trace_dive_finds_db_culprit(state, deps):
    out = trace_dive.make(deps)(state)
    trace_evs = [e for e in out.evidence if e.kind == EvidenceKind.trace]
    assert len(trace_evs) == 2
    first = trace_evs[0]
    assert first.data["span_name"] == "SELECT products"
    assert "pg_sleep" in first.summary
    assert first.links[0].startswith("http://localhost:8080/trace/")


def test_pick_culprit_prefers_high_self_time_over_instant_error_span():
    # Live hero-run shape: gateway root -> catalog handler -> 25s SELECT, and
    # gateway also emits a ~0ms erroring 502 "http send" span. The culprit is
    # the span where the time went (the SELECT), not the error-forwarding span.
    from argus.models import SpanInfo
    spans = [
        SpanInfo(span_id="root", name="GET /api/products", service="gateway",
                 duration_ms=25000, has_error=True),
        SpanInfo(span_id="send", parent_span_id="root",
                 name="GET /api/products http send", service="gateway",
                 duration_ms=0.2, has_error=True,
                 attributes={"http.status_code": "502"}),
        SpanInfo(span_id="handler", parent_span_id="root", name="GET /products",
                 service="catalog", duration_ms=24900),
        SpanInfo(span_id="select", parent_span_id="handler",
                 name="SELECT products", service="catalog", duration_ms=24800,
                 attributes={"db.statement": "SELECT *, pg_sleep(25) FROM products"}),
    ]
    culprit = trace_dive.pick_culprit(spans)
    assert culprit is not None and culprit.span_id == "select"


def test_pick_culprit_prefers_erroring_span_with_real_self_time():
    from argus.models import SpanInfo
    spans = [
        SpanInfo(span_id="root", name="GET /checkout", duration_ms=3200),
        SpanInfo(span_id="db", parent_span_id="root", name="SELECT",
                 duration_ms=2900, has_error=True),
    ]
    culprit = trace_dive.pick_culprit(spans)
    assert culprit is not None and culprit.span_id == "db"


def test_pick_culprit_no_hierarchy_ignores_instant_error_spans():
    from argus.models import SpanInfo
    spans = [
        SpanInfo(span_id="a", name="http send", duration_ms=0.1, has_error=True),
        SpanInfo(span_id="b", name="GET /products", duration_ms=3000, has_error=True),
        SpanInfo(span_id="c", name="SELECT products", duration_ms=2900, has_error=True),
    ]
    culprit = trace_dive.pick_culprit(spans)
    assert culprit is not None and culprit.span_id == "c"


def test_db_statement_flows_into_hypothesize_prompt(state, deps):
    # The culprit span's db.statement must reach the LLM so it can name the
    # actual query (pg_sleep) rather than a symptom-level cause.
    out = trace_dive.make(deps)(state)
    prompt = hypothesize.build_user_prompt(out)
    assert "pg_sleep" in prompt
    assert "db.statement" in prompt


def test_trace_dive_no_traces_degrades(state, deps, monkeypatch):
    monkeypatch.setattr(deps.signoz, "search_error_traces", lambda *a, **k: [])
    monkeypatch.setattr(deps.signoz, "search_slow_traces", lambda *a, **k: [])
    out = trace_dive.make(deps)(state)
    evs = [e for e in out.evidence if e.kind == EvidenceKind.trace]
    assert len(evs) == 1 and evs[0].unavailable


def test_log_corr_novel_signatures(state, deps):
    state = trace_dive.make(deps)(state)  # provides trace ids for correlation
    out = log_corr.make(deps)(state)
    log_evs = [e for e in out.evidence if e.kind == EvidenceKind.log]
    assert log_evs, "expected clustered log signatures"
    assert all(e.data["novel"] for e in log_evs)
    templates = " ".join(e.data["template"] for e in log_evs)
    assert "<*>" in templates  # numbers templated out
    assert "statement timeout" in templates


def test_log_template_clustering():
    c = log_corr.cluster([
        "payment 4812 failed after 300 ms",
        "payment 9931 failed after 251 ms",
        "user a1b2c3d4e5f6a7b8 logged out",
    ])
    assert c["payment <*> failed after <*> ms"] == 2
    assert len(c) == 2


def test_infra_unavailable_marker(state, deps):
    out = infra.make(deps)(state)
    evs = [e for e in out.evidence if e.kind == EvidenceKind.infra]
    assert len(evs) == 1 and evs[0].unavailable


def test_change_corr_no_deploys(state, deps):
    out = change_corr.make(deps)(state)
    evs = [e for e in out.evidence if e.kind == EvidenceKind.change]
    assert len(evs) == 1 and evs[0].unavailable


def test_change_corr_uses_context_qualified_event_key():
    """Regression for the bug ARGUS found in ITSELF (meta-investigation
    inv-a2a0b2e215): the bare filter key `event.name` makes SigNoz's
    expression parser 400 whenever no deployment event was ever ingested
    ("key `name` not found", verified live on v0.132.2). The filter must use
    the context-qualified `attribute.event.name` form, which parses cleanly
    and returns zero rows instead."""
    assert change_corr.DEPLOYMENT_FILTER == "attribute.event.name = 'deployment'"

    captured: list[str] = []

    class _Signoz:
        def search_logs(self, expr, window, tag):
            captured.append(expr)
            return []

    from datetime import datetime, timezone

    from argus.models import Alert, InvestigationState, TimeWindow
    from argus.nodes import Deps

    state = InvestigationState(investigation_id="inv-t", alert=Alert())
    state.window = TimeWindow(
        start=datetime(2026, 7, 17, tzinfo=timezone.utc),
        end=datetime(2026, 7, 17, 1, tzinfo=timezone.utc),
    )
    change_corr.make(Deps(signoz=_Signoz(), links=None, llm=None))(state)
    assert captured == ["attribute.event.name = 'deployment'"]


def test_hypothesize_parses_and_tracks_cost(state, deps):
    out = hypothesize.make(deps)(state)
    assert out.iteration == 1
    assert 2 <= len(out.hypotheses) <= 4
    assert all(h.verdict == Verdict.pending for h in out.hypotheses)
    assert out.usage.llm_calls == 1
    assert out.usage.cost_usd > 0


def test_verify_confirms_and_refutes(state, deps):
    state = hypothesize.make(deps)(state)
    out = verify.make(deps)(state)
    verdicts = [h.verdict for h in out.hypotheses]
    assert verdicts.count(Verdict.confirmed) == 1
    assert verdicts.count(Verdict.refuted) == 2
    confirmed = next(h for h in out.hypotheses if h.verdict == Verdict.confirmed)
    assert "ratio" in confirmed.verdict_detail


def test_route_after_verify():
    from argus.models import Expected, Hypothesis, VerificationKind, VerificationSpec

    def hyp(verdict):
        return Hypothesis(
            claim="c", mechanism="m", confidence=0.5, verdict=verdict,
            verification=VerificationSpec(
                kind=VerificationKind.log_check,
                expected=Expected(op="contains", value="x"),
            ),
        )

    class S:
        max_iterations = 2

    s = S()
    s.iteration = 1
    s.hypotheses = [hyp(Verdict.confirmed), hyp(Verdict.refuted)]
    assert verify.route_after_verify(s) == "report"
    s.hypotheses = [hyp(Verdict.refuted)]
    assert verify.route_after_verify(s) == "hypothesize"
    s.iteration = 2
    assert verify.route_after_verify(s) == "report"
