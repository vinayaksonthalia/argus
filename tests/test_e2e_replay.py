"""Full-graph replay over fixtures/incident-1 — this IS the demo, as a test."""

from argus.evals import format_scorecard, run_eval
from argus.investigation import run_investigation
from argus.models import Verdict


def test_full_investigation_replay(alert, deps):
    visited: list[str] = []
    state = run_investigation(alert, deps, on_node=lambda n, s: visited.append(n))

    assert visited[:6] == ["triage", "golden_signals", "trace_dive", "log_corr", "infra", "change_corr"]
    assert visited[-2:] == ["report", "act"]

    # RCA correctness
    report = state.report
    assert report is not None and not report.degraded
    assert "pg_sleep" in report.root_cause
    assert "catalog" in report.root_cause.lower()
    assert report.confidence >= 0.8

    # Hypothesis verdicts: exactly one confirmed, others refuted
    verdicts = [h.verdict for h in state.hypotheses]
    assert verdicts.count(Verdict.confirmed) == 1
    assert verdicts.count(Verdict.refuted) == 2

    # Every evidence link is a SigNoz URL
    assert report.links and all(l.startswith("http://localhost:8080") for l in report.links)

    # Cost tracking worked offline
    assert state.usage.llm_calls == 1
    assert state.usage.input_tokens > 0 and state.usage.cost_usd > 0

    # Slack blocks + postmortem produced
    assert report.slack_blocks[0]["type"] == "header"
    assert "Root cause" in report.postmortem_md
    assert "pg_sleep" in report.postmortem_md


def test_graph_degrades_to_report_on_hard_node_failure(alert, deps, monkeypatch):
    """A hypothesize failure must yield an evidence-only report, never a hang (NFR-4)."""

    def boom(*a, **k):
        raise RuntimeError("LLM unreachable")

    monkeypatch.setattr(deps.llm, "complete", boom)
    state = run_investigation(alert, deps)
    assert state.report is not None
    assert state.report.degraded
    assert any("hypothesize" in e for e in state.errors)
    assert state.report.evidence_bullets  # evidence still reported


def test_eval_harness_scores_incident1(fixture_dir):
    result = run_eval(fixture_dir)
    card = format_scorecard([result])
    assert result.passed, card
    assert result.checks["root_cause_keywords"]
    assert result.checks["hypotheses_confirmed"]
    assert result.checks["cost_within_budget"]
    assert "1/1 cases passed" in card
