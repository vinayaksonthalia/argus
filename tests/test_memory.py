"""Incident memory: embedding, store/recall, node injection, RCA citation."""

from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from argus.memory import (
    IncidentMemory,
    IncidentRecord,
    cosine,
    embed,
    record_from_state,
)
from argus.models import (
    Alert,
    Evidence,
    EvidenceKind,
    InvestigationState,
    Report,
)
from argus.nodes import Deps, memory_recall
from argus.nodes.memory_recall import CITE_SIMILARITY, build_query_text


def _record(inc_id: str, root_cause: str, service: str = "catalog",
             alert: str = "catalog p99 latency > 1s", degraded: bool = False) -> IncidentRecord:
    return IncidentRecord(
        incident_id=inc_id,
        occurred_at="2026-07-16T22:47:00+00:00",
        alert_name=alert,
        service=service,
        symptoms="p99 latency jumped; slow SELECT on products; pg_sleep in db.statement",
        root_cause=root_cause,
        confidence=0.9,
        degraded=degraded,
    )


# ------------------------------------------------------------ embedding


def test_embed_deterministic_and_normalized():
    a = embed("pg_sleep slow query catalog postgres")
    b = embed("pg_sleep slow query catalog postgres")
    assert a == b
    assert abs(sum(x * x for x in a) - 1.0) < 1e-9


def test_similar_texts_score_higher_than_unrelated():
    base = embed("catalog p99 latency pg_sleep slow postgres SELECT query")
    similar = embed("slow postgres query pg_sleep raised catalog latency p99")
    unrelated = embed("payments 502 error storm upstream connection reset")
    assert cosine(base, similar) > cosine(base, unrelated)
    assert cosine(base, similar) > 0.5


def test_embed_empty_text_is_zero_vector():
    assert all(v == 0.0 for v in embed(""))


# ------------------------------------------------------------ store / recall


def test_store_and_recall_ranks_same_failure_class_first(tmp_path):
    mem = IncidentMemory(tmp_path / "mem.db")
    mem.store(_record("inv-slowdb", "pg_sleep(2.5) injected into catalog's product SELECT"))
    mem.store(_record("inv-errors", "payments upstream connection reset by peer",
                      service="payments", alert="payments error rate"))
    matches = mem.recall("catalog latency pg_sleep slow SELECT postgres", top_k=3)
    assert matches
    assert matches[0][1].incident_id == "inv-slowdb"
    assert matches[0][0] > matches[-1][0] or len(matches) == 1


def test_recall_excludes_self_and_honors_min_similarity(tmp_path):
    mem = IncidentMemory(tmp_path / "mem.db")
    mem.store(_record("inv-self", "pg_sleep in catalog SELECT"))
    assert mem.recall("pg_sleep catalog SELECT", exclude_id="inv-self") == []
    assert mem.recall("zebra quantum harpsichord", min_similarity=0.5) == []


def test_store_is_idempotent_by_incident_id(tmp_path):
    mem = IncidentMemory(tmp_path / "mem.db")
    mem.store(_record("inv-1", "cause A"))
    mem.store(_record("inv-1", "cause B (updated)"))
    assert mem.count() == 1
    assert mem.all()[0].root_cause == "cause B (updated)"


def test_record_from_state_condenses_report_and_evidence():
    state = _state_with_evidence()
    state.report = Report(title="t", root_cause="pg_sleep in SELECT", confidence=0.9,
                          impact="p99 8x")
    rec = record_from_state(state)
    assert rec.incident_id == state.investigation_id
    assert rec.service == "catalog"
    assert "pg_sleep" in rec.root_cause
    assert "p99 jumped" in rec.symptoms


# ------------------------------------------------------------ recall node


def _state_with_evidence() -> InvestigationState:
    state = InvestigationState(
        investigation_id="inv-new",
        alert=Alert(labels={"alertname": "catalog p99 latency > 1s",
                            "service.name": "catalog"}),
        service="catalog",
    )
    state.add_evidence(Evidence(
        kind=EvidenceKind.metric, source="golden_signals.p99",
        summary="p99 jumped 8.4x; slow SELECT pg_sleep visible in catalog postgres spans",
    ))
    return state


def _deps(memory=None) -> Deps:
    return Deps(signoz=None, links=None, llm=None, memory=memory)


def test_node_injects_similar_incident_as_memory_evidence(tmp_path):
    mem = IncidentMemory(tmp_path / "mem.db")
    mem.store(_record("inv-hero", "pg_sleep(2.5) injected into catalog product SELECT"))
    state = memory_recall.make(_deps(mem))(_state_with_evidence())
    mem_evs = [e for e in state.available_evidence() if e.kind == EvidenceKind.memory]
    assert len(mem_evs) == 1
    ev = mem_evs[0]
    assert "inv-hero" in ev.summary
    assert "root cause was" in ev.summary
    assert "Jul 16" in ev.summary
    assert 0 < ev.data["similarity"] <= 1


def test_node_marks_unavailable_when_no_memory_or_no_match(tmp_path):
    state = memory_recall.make(_deps(None))(_state_with_evidence())
    assert any(e.kind == EvidenceKind.memory and e.unavailable for e in state.evidence)
    assert not [e for e in state.available_evidence() if e.kind == EvidenceKind.memory]

    empty = IncidentMemory(tmp_path / "empty.db")
    state2 = memory_recall.make(_deps(empty))(_state_with_evidence())
    assert any(e.kind == EvidenceKind.memory and e.unavailable for e in state2.evidence)


def test_build_query_text_excludes_memory_evidence():
    state = _state_with_evidence()
    state.add_evidence(Evidence(kind=EvidenceKind.memory, source="memory.recall",
                                summary="SHOULD NOT FEED BACK"))
    text = build_query_text(state)
    assert "SHOULD NOT FEED BACK" not in text
    assert "catalog" in text


# ------------------------------------------------------------ RCA citation


def test_report_cites_high_similarity_memory(monkeypatch):
    from argus.nodes import report as report_node

    state = _state_with_evidence()
    state.add_evidence(Evidence(
        kind=EvidenceKind.memory, source="memory.recall",
        summary="similar to incident inv-hero (Jul 16, similarity 82%): root cause was X",
        data={"incident_id": "inv-hero", "similarity": 0.82},
    ))
    from argus.models import Expected, Hypothesis, Verdict, VerificationKind, VerificationSpec

    state.hypotheses = [Hypothesis(
        claim="slow SELECT", mechanism="pg_sleep stalls the pool", confidence=0.9,
        verification=VerificationSpec(
            kind=VerificationKind.log_check, params={},
            expected=Expected(op="contains", value="pg_sleep"),
        ),
        verdict=Verdict.confirmed, verdict_detail="found",
    )]

    class _Stats:
        def summary(self):
            return "1 query"

    class _Signoz:
        stats = _Stats()

    deps = Deps(signoz=_Signoz(), links=None, llm=None)
    state = report_node.make(deps)(state)
    assert "inv-hero" in state.report.root_cause
    assert "82%" in state.report.root_cause
    assert "Similar past incidents" in state.report.postmortem_md
    assert "inv-hero" in state.report.postmortem_md


def test_report_does_not_cite_low_similarity():
    from argus.nodes import report as report_node

    state = _state_with_evidence()
    state.add_evidence(Evidence(
        kind=EvidenceKind.memory, source="memory.recall",
        summary="weak match", data={"incident_id": "inv-weak",
                                    "similarity": CITE_SIMILARITY - 0.1},
    ))

    class _Signoz:
        stats = None

    state = report_node.make(Deps(signoz=_Signoz(), links=None, llm=None))(state)
    assert "inv-weak" not in state.report.root_cause
    # still listed in the postmortem section for transparency
    assert "Similar past incidents" in state.report.postmortem_md
