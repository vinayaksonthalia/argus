"""Trace-dive node: exemplar failing traces -> walk the span tree to the
deepest erroring span (fallback: longest duration) and extract db.statement /
http.url / exception events, scrubbed (FR-4)."""

from __future__ import annotations

from ..models import Evidence, EvidenceKind, InvestigationState, SpanInfo
from ..security import cap_line
from . import Deps

INTERESTING_ATTRS = ("db.statement", "db.system", "http.url", "http.route",
                     "http.status_code", "exception.type", "exception.message",
                     "rpc.system", "messaging.system", "service.version")


def self_times(spans: list[SpanInfo]) -> dict[str, float]:
    """Per-span self-time: duration minus the direct children's durations —
    the work each span did itself (needs parent_span_id on the rows)."""
    child_time: dict[str, float] = {}
    for s in spans:
        if s.parent_span_id:
            child_time[s.parent_span_id] = child_time.get(s.parent_span_id, 0.0) + s.duration_ms
    return {s.span_id: max(s.duration_ms - child_time.get(s.span_id, 0.0), 0.0) for s in spans}


def pick_culprit(spans: list[SpanInfo]) -> SpanInfo | None:
    """The span where the time (or the failure) actually happened.

    Primary rule: the highest **self-time** span — this surfaces catalog's
    25-second SELECT (all self-time, carries db.statement) over the gateway's
    0ms error-forwarding "http send" span in the same trace. An erroring span
    is preferred only when it carries comparable self-time of its own; a
    near-instant error span is a symptom, not a culprit.

    Fallback (rows without parent_span_id, e.g. older fixtures): deepest
    erroring work approximated as the erroring span with the smallest
    non-trivial duration; near-instant error spans are ignored.
    """
    if not spans:
        return None
    if any(s.parent_span_id for s in spans):
        st = self_times(spans)
        top = max(spans, key=lambda s: st[s.span_id])
        top_self = st[top.span_id]
        errored = [s for s in spans
                   if s.has_error and st[s.span_id] > 0 and st[s.span_id] >= 0.5 * top_self]
        if errored:
            return max(errored, key=lambda s: st[s.span_id])
        return top
    max_dur = max(s.duration_ms for s in spans)
    floor = max(1.0, 0.01 * max_dur)
    errored = [s for s in spans if s.has_error and s.duration_ms >= floor]
    if errored:
        return min(errored, key=lambda s: s.duration_ms)
    return max(spans, key=lambda s: s.duration_ms)


def make(deps: Deps):
    def trace_dive(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        exemplars = deps.signoz.search_error_traces(
            state.service, state.window, limit=3, tag="traces.search"
        )
        if not exemplars:
            # Latency incidents often have no errored spans at all — fall back
            # to the slowest traces for the service in the window.
            exemplars = deps.signoz.search_slow_traces(
                state.service, state.window, limit=3, tag="traces.search.slow"
            )
        if not exemplars:
            state.add_evidence(Evidence(
                kind=EvidenceKind.trace, source="trace_dive",
                summary="no failing or unusually slow traces found in the alert window",
                unavailable=True,
            ))
            return state

        for i, row in enumerate(exemplars[:3]):
            trace_id = str(row.get("trace_id", ""))
            if not trace_id:
                continue
            spans = deps.signoz.trace_spans(trace_id, state.window, tag=f"traces.detail.{i}")
            culprit = pick_culprit(spans)
            if culprit is None:
                continue
            details = {
                k: cap_line(v) for k, v in culprit.attributes.items() if k in INTERESTING_ATTRS
            }
            detail_str = "; ".join(f"{k}={v}" for k, v in sorted(details.items()))
            events = "; ".join(cap_line(e, 200) for e in culprit.events[:3])
            summary = (
                f"exemplar trace {trace_id[:16]}…: culprit span '{culprit.name}' "
                f"(service={culprit.service}, {culprit.duration_ms:.0f}ms, "
                f"error={culprit.has_error})"
            )
            if detail_str:
                summary += f" | {detail_str}"
            if events:
                summary += f" | events: {events}"
            state.add_evidence(Evidence(
                kind=EvidenceKind.trace,
                source=f"trace_dive.exemplar.{i}",
                summary=summary,
                data={"trace_id": trace_id, "span_id": culprit.span_id,
                      "span_name": culprit.name, "span_service": culprit.service,
                      "duration_ms": culprit.duration_ms, "attributes": details},
                links=[deps.links.trace(trace_id, culprit.span_id)],
            ))
        return state

    return trace_dive
