"""Schema validation + repair behavior for hypothesis JSON (FR-6, risk R4)."""

import json

import pytest

from argus.llm import LLMResult
from argus.nodes import hypothesize

VALID = [{
    "claim": "db slow",
    "mechanism": "pool saturation",
    "confidence": 0.8,
    "verification": {
        "kind": "query_range",
        "params": {"signal": "traces", "aggregation": "count()", "filter_expression": ""},
        "expected": {"op": "gt", "value": 1, "description": "d"},
    },
}]


def test_parse_valid():
    hyps = hypothesize.parse_hypotheses(json.dumps(VALID))
    assert hyps[0].claim == "db slow"


def test_parse_strips_markdown_fences():
    text = "Here you go:\n```json\n" + json.dumps(VALID) + "\n```"
    assert len(hypothesize.parse_hypotheses(text)) == 1


def test_parse_rejects_bad_confidence():
    bad = json.loads(json.dumps(VALID))
    bad[0]["confidence"] = 3.0
    with pytest.raises(Exception):
        hypothesize.parse_hypotheses(json.dumps(bad))


def test_parse_rejects_empty_claim():
    bad = json.loads(json.dumps(VALID))
    bad[0]["claim"] = "  "
    with pytest.raises(Exception):
        hypothesize.parse_hypotheses(json.dumps(bad))


def test_parse_rejects_unknown_kind():
    bad = json.loads(json.dumps(VALID))
    bad[0]["verification"]["kind"] = "delete_everything"
    with pytest.raises(Exception):
        hypothesize.parse_hypotheses(json.dumps(bad))


def test_parse_rejects_no_array():
    with pytest.raises(hypothesize.HypothesisParseError):
        hypothesize.parse_hypotheses("I could not decide.")


class FlakyLLM:
    """First answer malformed, repair answer valid — exercises the retry path."""

    def __init__(self):
        self.calls = []

    def complete(self, system, user, tag, max_tokens=2000):
        self.calls.append(tag)
        text = "oops no json" if len(self.calls) == 1 else json.dumps(VALID)
        return LLMResult(text=text, model="test", input_tokens=10, output_tokens=5)


def test_hypothesize_repair_retry(state, deps):
    flaky = FlakyLLM()
    deps.llm = flaky
    out = hypothesize.make(deps)(state)
    assert flaky.calls == ["hypothesize.1", "hypothesize.1.repair"]
    assert len(out.hypotheses) == 1
    assert out.usage.llm_calls == 2  # both calls billed


def test_prompt_wraps_all_telemetry(state, deps):
    """NFR-7: alert + evidence text must be inside <telemetry> blocks."""
    from argus.nodes import golden_signals

    state = golden_signals.make(deps)(state)
    prompt = hypothesize.build_user_prompt(state)
    assert '<telemetry name="alert">' in prompt
    assert '<telemetry name="evidence.metric">' in prompt
    # No evidence summary appears outside a telemetry block.
    before_first_block = prompt.split("<telemetry", 1)[0]
    assert "golden_signals" not in before_first_block
