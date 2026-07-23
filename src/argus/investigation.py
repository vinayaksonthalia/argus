"""Wire the investigation graph and run it end-to-end.

triage → golden_signals → trace_dive → log_corr → infra → change_corr →
hypothesize ⇄ verify (max N iterations) → report
"""

from __future__ import annotations

import uuid
from typing import Callable, Optional

from .graph import END, Graph
from .models import Alert, InvestigationState
from .nodes import (
    Deps,
    act,
    change_corr,
    golden_signals,
    hypothesize,
    infra,
    log_corr,
    memory_recall,
    report,
    trace_dive,
    triage,
    verify,
)
from .telemetry import tracer


def build_graph(deps: Deps, ) -> Graph:
    g = Graph(entry="triage")
    g.add_node("triage", triage.make(deps))
    g.add_node("golden_signals", golden_signals.make(deps))
    g.add_node("trace_dive", trace_dive.make(deps), optional=True)
    g.add_node("log_corr", log_corr.make(deps), optional=True)
    g.add_node("infra", infra.make(deps), optional=True)
    g.add_node("change_corr", change_corr.make(deps), optional=True)
    g.add_node("memory_recall", memory_recall.make(deps), optional=True)
    g.add_node("hypothesize", hypothesize.make(deps))
    g.add_node("verify", verify.make(deps))
    g.add_node("report", report.make(deps))
    g.add_node("act", act.make(deps), optional=True)

    g.add_edge("triage", "golden_signals")
    g.add_edge("golden_signals", "trace_dive")
    g.add_edge("trace_dive", "log_corr")
    g.add_edge("log_corr", "infra")
    g.add_edge("infra", "change_corr")
    g.add_edge("change_corr", "memory_recall")
    g.add_edge("memory_recall", "hypothesize")
    g.add_edge("hypothesize", "verify")
    g.add_conditional_edge("verify", verify.route_after_verify)
    g.add_edge("report", "act")
    g.add_edge("act", END)
    return g


def run_investigation(
    alert: Alert,
    deps: Deps,
    max_iterations: int = 2,
    on_node: Optional[Callable[[str, float], None]] = None,
    investigation_id: Optional[str] = None,
) -> InvestigationState:
    state = InvestigationState(
        investigation_id=investigation_id or f"inv-{uuid.uuid4().hex[:10]}",
        alert=alert,
        max_iterations=max_iterations,
    )
    graph = build_graph(deps)
    with tracer().start_as_current_span("argus.investigation") as span:
        span.set_attribute("argus.investigation_id", state.investigation_id)
        span.set_attribute("argus.alert.name", alert.name)
        state = graph.run(state, on_node=on_node)
        span.set_attribute("argus.service", state.service)
        span.set_attribute("argus.cost.usd", round(state.usage.cost_usd, 6))
        span.set_attribute("gen_ai.usage.input_tokens", state.usage.input_tokens)
        span.set_attribute("gen_ai.usage.output_tokens", state.usage.output_tokens)
        span.set_attribute("argus.degraded", bool(state.report and state.report.degraded))
    if deps.memory is not None and state.report is not None:
        # Learn from this investigation: store its signature for future recall.
        from .memory import record_from_state

        deps.memory.store(record_from_state(state))
    return state
