"""Tests for the new LLM providers (claude-cli, heuristic), provider
selection, and query-cost (meta.rowsScanned) tracking."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest

from argus.config import Settings
from argus.llm import (
    ClaudeCliError,
    ClaudeCliProvider,
    HeuristicProvider,
    make_provider,
)
from argus.nodes.hypothesize import parse_hypotheses
from argus.signoz.transport import QueryStats

# ------------------------------------------------------------ heuristic


def test_heuristic_provider_emits_valid_hypotheses():
    provider = HeuristicProvider()
    user = (
        "Alert 'HighLatency' is firing for service 'catalog'.\n"
        "evidence: db.statement SELECT ... pg_sleep(2.5); ERROR logs spiking; deployment event seen"
    )
    result = provider.complete("system", user, tag="hypothesize.1")
    assert result.model == "heuristic-v1"
    assert result.cost_usd == 0.0
    hypotheses = parse_hypotheses(result.text)
    assert 1 <= len(hypotheses) <= 4
    assert any("catalog" in h.claim for h in hypotheses)
    # deterministic: same input -> same output
    assert provider.complete("system", user, tag="x").text == result.text


def test_heuristic_provider_fallback_hypothesis():
    provider = HeuristicProvider()
    result = provider.complete("s", "Alert 'X' is firing for service 'gw'. nothing informative", "t")
    hypotheses = parse_hypotheses(result.text)
    assert len(hypotheses) >= 1
    assert hypotheses[0].verification.kind.value == "query_range"


# ------------------------------------------------------------ claude-cli


CLI_ENVELOPE = {
    "type": "result",
    "is_error": False,
    "result": '[{"claim": "x", "mechanism": "y", "confidence": 0.5, "verification": {"kind": "query_range", "params": {"signal": "traces", "aggregation": "count()", "filter_expression": "service.name = \'a\'"}, "expected": {"op": "gt", "value": 1, "description": "d"}}}]',
    "total_cost_usd": 0.0123,
    "usage": {"input_tokens": 10, "cache_read_input_tokens": 5,
              "cache_creation_input_tokens": 100, "output_tokens": 42},
    "modelUsage": {"claude-sonnet-4-5-20250929": {}},
}


def test_claude_cli_provider_parses_envelope(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")

    def fake_run(cmd, **kwargs):
        assert "-p" in cmd and "--output-format" in cmd
        return SimpleNamespace(returncode=0, stdout=json.dumps(CLI_ENVELOPE), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    provider = ClaudeCliProvider(model="sonnet")
    result = provider.complete("sys", "user", tag="hypothesize.1")
    assert result.model == "claude-sonnet-4-5-20250929"
    assert result.input_tokens == 115  # input + cache_read + cache_creation
    assert result.output_tokens == 42
    assert result.cost_usd == pytest.approx(0.0123)  # provider-reported, not estimated
    assert parse_hypotheses(result.text)


def test_claude_cli_provider_error_paths(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    provider = ClaudeCliProvider(model="sonnet", timeout_s=1)

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=1, stdout="", stderr="boom"))
    with pytest.raises(ClaudeCliError, match="exited 1"):
        provider.complete("s", "u", "t")

    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: SimpleNamespace(returncode=0, stdout="not json", stderr=""))
    with pytest.raises(ClaudeCliError, match="non-JSON"):
        provider.complete("s", "u", "t")


def test_claude_cli_missing_binary(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    with pytest.raises(ClaudeCliError, match="not found"):
        ClaudeCliProvider()


# ------------------------------------------------------------ provider selection


def test_provider_auto_resolution(monkeypatch):
    s = Settings(anthropic_api_key="sk-ant-real-key-123", llm_provider="auto")
    assert s.resolved_llm_provider() == "anthropic"

    s = Settings(anthropic_api_key="", llm_provider="auto")
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    assert s.resolved_llm_provider() == "claude-cli"
    monkeypatch.setattr("shutil.which", lambda _: None)
    assert s.resolved_llm_provider() == "heuristic"


def test_validate_live_does_not_require_anthropic_key_for_cli(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: "/usr/bin/claude")
    s = Settings(signoz_api_key="real-signoz-key-abc", llm_provider="claude-cli")
    s.validate_live()  # must not raise
    assert s.validated


def test_make_provider_heuristic():
    s = Settings(llm_provider="heuristic")
    assert isinstance(make_provider(s), HeuristicProvider)


def test_make_provider_unknown():
    s = Settings(llm_provider="nope")
    with pytest.raises(ValueError, match="unknown ARGUS_LLM_PROVIDER"):
        make_provider(s)


# ------------------------------------------------------------ query stats


def test_query_stats_records_meta():
    stats = QueryStats()
    stats.record("golden.p99.after", {
        "data": {"meta": {"rowsScanned": 1000, "bytesScanned": 2_000_000, "durationMs": 25}}
    })
    stats.record("verify.1.0", {"data": {"meta": {"rowsScanned": 500}}})
    stats.record("no.meta", {"data": {}})
    assert stats.queries == 3
    assert stats.rows_scanned == 1500
    assert stats.bytes_scanned == 2_000_000
    assert stats.by_tag["golden.p99.after"] == 1000
    assert "3 SigNoz queries" in stats.summary()
    assert "1,500 rows" in stats.summary()


def test_replay_run_labels_llm_as_recorded():
    from argus.evals import load_alert, make_replay_deps
    from argus.investigation import run_investigation

    deps = make_replay_deps("fixtures/incident-1")
    state = run_investigation(load_alert("fixtures/incident-1"), deps)
    assert state.report is not None
    assert "RECORDED" in state.report.llm_label
    assert state.report.query_stats  # rowsScanned flowed through replay too
    assert state.report.timeline  # timeline reconstructed


def test_self_diagnosis_on_degraded_report():
    from argus.models import (Alert, Evidence, EvidenceKind, Expected, Hypothesis,
                              InvestigationState, VerificationKind, VerificationSpec, Verdict)
    from argus.nodes.report import build_self_diagnosis

    state = InvestigationState(investigation_id="inv-x", alert=Alert(labels={"alertname": "A"}))
    state.evidence.append(Evidence(kind=EvidenceKind.trace, source="trace_dive",
                                   summary="no traces", unavailable=True))
    state.errors.append("node 'infra' failed: boom")
    state.hypotheses.append(Hypothesis(
        claim="c", mechanism="m", confidence=0.5, verdict=Verdict.refuted,
        verdict_detail="count = 0 (need > 5)",
        verification=VerificationSpec(kind=VerificationKind.query_range,
                                      expected=Expected(op="gt", value=5)),
    ))
    text = build_self_diagnosis(state)
    assert "self-diagnosis" in text
    assert "trace_dive" in text and "boom" in text and "need > 5" in text


def test_openai_compat_provider_parses_response(monkeypatch):
    import httpx as _httpx

    from argus.llm import OpenAICompatProvider

    def fake_post(url, **kwargs):
        assert url.endswith("/chat/completions")
        assert kwargs["json"]["messages"][0]["role"] == "system"
        req = _httpx.Request("POST", url)
        return _httpx.Response(200, json={
            "model": "llama-3.3-70b-versatile",
            "choices": [{"message": {"content": "[]"}}],
            "usage": {"prompt_tokens": 100, "completion_tokens": 20},
        }, request=req)

    monkeypatch.setattr(_httpx, "post", fake_post)
    p = OpenAICompatProvider("https://api.groq.com/openai/v1", "key", "llama-3.3-70b-versatile", "groq")
    r = p.complete("sys", "user", "t")
    assert r.model == "groq:llama-3.3-70b-versatile"
    assert (r.input_tokens, r.output_tokens) == (100, 20)
    assert r.cost_usd == 0.0  # free tier


def test_openai_compat_requires_key():
    from argus.llm import OpenAICompatProvider
    with pytest.raises(ValueError, match="no API key"):
        OpenAICompatProvider("https://api.cerebras.ai/v1", "", "m", "cerebras")


def test_auto_resolution_prefers_groq_over_heuristic(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda _: None)
    s = Settings(llm_provider="auto", groq_api_key="gsk_realkey123")
    assert s.resolved_llm_provider() == "groq"
