"""Draft alert rules (FR-15) + the spend meta-alert factory (row 9): the
model's confirmed verification spec maps onto a DISABLED draft threshold rule
— never auto-enabled — and unmappable specs are skipped, not forced."""

from __future__ import annotations

from argus.models import (
    Alert,
    Expected,
    Hypothesis,
    InvestigationState,
    Report,
    Verdict,
    VerificationKind,
    VerificationSpec,
)
from argus.nodes import Deps, act
from argus.signoz.rules import (
    DRAFT_PREFIX,
    cost_meta_alert_rule,
    draft_rule_from_hypothesis,
)


def _draft(op: str, value, kind_params=None):
    params = {"signal": "logs", "filter_expression": "service.name = 'catalog'",
              **(kind_params or {})}
    return draft_rule_from_hypothesis(
        service="catalog", investigation_id="inv-test", alert_name="p99 alert",
        claim="catalog times out under load",
        spec_params={**params, "op": op, "expected_value": value},
        channels=[],
    )


def test_contains_spec_maps_to_disabled_count_rule():
    rule = _draft("contains", "timed out")
    assert rule is not None
    assert rule["disabled"] is True
    assert rule["alert"].startswith(DRAFT_PREFIX)
    assert rule["alertType"] == "LOGS_BASED_ALERT"
    spec = rule["condition"]["compositeQuery"]["queries"][0]["spec"]
    assert "timed out" in spec["filter"]["expression"]
    assert spec["aggregations"] == [{"expression": "count()"}]
    assert rule["labels"]["argus.draft"] == "true"
    # draft-safety invariant: description tells a human to enable it
    assert "ENABLE manually" in rule["annotations"]["description"]


def test_gt_spec_uses_value_as_threshold():
    rule = _draft("gt", 5, {"aggregation": "count()"})
    thr = rule["condition"]["thresholds"]["spec"][0]
    assert thr["target"] == 5.0 and thr["op"] == "above"


def test_unmappable_specs_return_none():
    # ratio_gt on a percentile has no rolling-window equivalent
    assert _draft("ratio_gt", 2, {"aggregation": "p99(duration_nano)"}) is None
    # missing filter expression
    assert draft_rule_from_hypothesis(
        "s", "inv", "a", "c", {"signal": "traces", "filter_expression": "",
                               "op": "gt", "expected_value": 1}, []) is None
    # unknown signal
    assert draft_rule_from_hypothesis(
        "s", "inv", "a", "c", {"signal": "metrics", "filter_expression": "x",
                               "op": "gt", "expected_value": 1}, []) is None


def test_meta_alert_rule_shape():
    rule = cost_meta_alert_rule(["argus-webhook"], threshold_usd_per_hour=0.5)
    assert rule["alertType"] == "METRIC_BASED_ALERT"
    agg = rule["condition"]["compositeQuery"]["queries"][0]["spec"]["aggregations"][0]
    assert agg["metricName"] == "argus.cost.usd"
    thr = rule["condition"]["thresholds"]["spec"][0]
    assert thr["target"] == 0.5 and thr["channels"] == ["argus-webhook"]
    assert rule["labels"]["service"] == "argus"


# ------------------------------------------------------------ act node


class _FakeRules:
    def __init__(self):
        self.created = []

    def create(self, rule):
        self.created.append(rule)
        return "rule-123"

    def rule_url(self, rule_id):
        return f"http://signoz/alerts/edit?ruleId={rule_id}"


def _state(verdict=Verdict.confirmed, op="contains", value="timed out"):
    state = InvestigationState(
        investigation_id="inv-act",
        alert=Alert(labels={"alertname": "p99", "service.name": "catalog"}),
        service="catalog",
    )
    state.hypotheses = [Hypothesis(
        claim="catalog is timing out", mechanism="overload", confidence=0.8,
        verification=VerificationSpec(
            kind=VerificationKind.log_check,
            params={"signal": "logs", "filter_expression": "service.name = 'catalog'"},
            expected=Expected(op=op, value=value),
        ),
        verdict=verdict, verdict_detail="found",
    )]
    state.report = Report(title="t", root_cause="rc", confidence=0.8, impact="i")
    return state


def test_act_creates_draft_rule_on_confirmed_hypothesis():
    rules = _FakeRules()
    deps = Deps(signoz=None, links=None, llm=None, dashboards=None, rules=rules)
    state = act.make(deps)(_state())
    assert len(rules.created) == 1
    assert rules.created[0]["disabled"] is True
    assert any("DRAFT follow-up alert rule" in b for b in state.report.evidence_bullets)
    assert "Draft follow-up alert" in state.report.postmortem_md


def test_act_skips_rule_when_nothing_confirmed_or_offline():
    rules = _FakeRules()
    deps = Deps(signoz=None, links=None, llm=None, dashboards=None, rules=rules)
    act.make(deps)(_state(verdict=Verdict.refuted))
    assert rules.created == []
    # offline: no rules client at all -> no crash
    deps_off = Deps(signoz=None, links=None, llm=None)
    state = act.make(deps_off)(_state())
    assert state.report is not None
