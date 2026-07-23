"""Golden-signals node: p99 latency, error rate, throughput with a
before/after comparison across the alert boundary (FR-3)."""

from __future__ import annotations

from ..models import Evidence, EvidenceKind, InvestigationState
from . import Deps


def _fmt_ratio(ratio: float) -> str:
    if ratio == float("inf"):
        return "from ~zero"
    if 0 <= ratio < 1.0:
        # "0.0x" reads like a rendering bug — show the drop as a percentage.
        return f"{ratio:.2f}x ({(1 - ratio):.0%} drop)"
    return f"{ratio:.1f}x"


def make(deps: Deps):
    def golden_signals(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        signals = deps.signoz.golden_signals(state.service, state.window)
        overview = deps.links.service_overview(state.service, state.window)

        units = {"p99_latency_ms": "ms", "error_rate": "", "throughput_per_min": "req/min"}
        for name, vals in signals.items():
            before, after, ratio = vals["before"], vals["after"], vals["ratio"]
            unit = units.get(name, "")
            if name == "error_rate":
                summary = (
                    f"error_rate: {before:.1%} before -> {after:.1%} after "
                    f"the alert boundary ({_fmt_ratio(ratio)})"
                )
            else:
                summary = (
                    f"{name}: {before:.1f}{unit} before -> {after:.1f}{unit} after "
                    f"the alert boundary ({_fmt_ratio(ratio)})"
                )
            state.add_evidence(
                Evidence(
                    kind=EvidenceKind.metric,
                    source=f"golden_signals.{name}",
                    summary=summary,
                    data={"before": before, "after": after,
                          "ratio": ratio if ratio != float("inf") else -1},
                    links=[overview],
                )
            )
        return state

    return golden_signals
