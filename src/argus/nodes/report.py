"""Report node (FR-8): assemble the RCA — Slack Block Kit message where every
claim deep-links into SigNoz, plus a markdown postmortem draft."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from ..models import Evidence, InvestigationState, Report, Verdict
from ..slack import build_blocks
from . import Deps


# Below this the RCA is flagged for human review.
REVIEW_THRESHOLD = float(os.getenv("ARGUS_REVIEW_THRESHOLD", "0.75"))
# Adaptive threshold: when incident memory recalls the same failure class AND
# that past incident was itself verified, the bar drops by this much — "we
# have seen this before and were right" is earned confidence. 0 disables.
MEMORY_TRUST_DISCOUNT = float(os.getenv("ARGUS_MEMORY_TRUST_DISCOUNT", "0.10"))
# The bar never drops below this, no matter how familiar the failure class.
THRESHOLD_FLOOR = 0.60


def _evidence_bullet(ev: Evidence) -> str:
    if ev.links:
        return f"{ev.summary} (<{ev.links[0]}|view in SigNoz>)"
    return ev.summary


def _fmt_ts(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%H:%M:%S UTC")


def build_timeline(state: InvestigationState) -> list[str]:
    """Reconstruct a chronological 'what happened when' from the collected
    evidence (incident.io-style timeline artifact)."""
    lines: list[str] = []
    if state.window:
        lines.append(f"{_fmt_ts(state.window.start)} — baseline window opens (pre-incident comparison)")
    for ev in state.available_evidence():
        if ev.kind.value == "change":
            lines.append(f"~alert window — change detected: {ev.summary}")
    if state.alert.starts_at:
        lines.append(f"{_fmt_ts(state.alert.starts_at)} — alert '{state.alert.name}' started firing")
    for ev in state.available_evidence():
        if ev.kind.value == "metric" and ev.data.get("ratio"):
            lines.append(f"alert window — {ev.summary}")
    began = f"{_fmt_ts(state.started_at)} — ARGUS investigation {state.investigation_id} began"
    if state.alert.starts_at and abs(
        (state.started_at - state.alert.starts_at).total_seconds()
    ) > 3600:
        # Replays reuse recorded alert timestamps against a live wall clock;
        # label the gap so the timeline can't read as an 18-hour response time.
        began += " (run at wall-clock time, after the recorded alert window)"
    lines.append(began)
    for h in state.hypotheses:
        if h.verdict == Verdict.confirmed:
            lines.append(f"{_fmt_ts(datetime.now(timezone.utc))} — hypothesis CONFIRMED: {h.claim}")
    return lines


def build_postmortem(state: InvestigationState, report: Report) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    memory_evs = [e for e in state.available_evidence() if e.kind.value == "memory"]
    memory_section = (
        ["## Similar past incidents (ARGUS memory)",
         *[f"- {e.summary}" for e in memory_evs], ""]
        if memory_evs else []
    )
    lines = [
        f"# Postmortem: {report.title}",
        "",
        f"- **Investigation:** `{state.investigation_id}`",
        f"- **Service:** `{state.service}`",
        f"- **Alert:** `{state.alert.name}`",
        f"- **Generated:** {now} (auto-drafted by ARGUS — review before publishing)",
        f"- **Confidence:** {report.confidence:.0%}" + ("  (DEGRADED: evidence-only)" if report.degraded else ""),
        f"- **Review bar:** {report.review_threshold:.0%}"
        + (f"  ({report.threshold_note})" if report.threshold_note else "  (default)"),
        "",
        "## Root cause",
        report.root_cause,
        ("" if not report.needs_review else
         "\n> ⚠ **Flagged for human review** — confidence below threshold "
         f"({report.confidence:.0%} < {report.review_threshold:.0%}) or no hypothesis verified.\n"),
        "## Impact",
        report.impact,
        "",
        "## Timeline",
        *[f"- {t}" for t in report.timeline],
        "",
        "## Evidence",
        *[f"- {ev.summary}" + (f" — {ev.links[0]}" if ev.links else "") for ev in state.available_evidence()],
        "",
        *memory_section,
        "## Hypotheses considered",
        *[
            f"- [{'UNVERIFIED — check failed to run' if h.verdict == Verdict.error else h.verdict.value.upper()}] "
            f"{h.claim} — {h.verdict_detail}"
            for h in state.hypotheses
        ],
        "",
        "## Cost",
        f"- LLM: {report.llm_label}",
        f"- LLM calls: {state.usage.llm_calls}, tokens: {state.usage.input_tokens} in / "
        f"{state.usage.output_tokens} out, est. ${state.usage.cost_usd:.4f}",
        *( [f"- Query footprint: {report.query_stats}"] if report.query_stats else [] ),
        "",
        "## Action items",
        "- [ ] Validate the root cause fix",
        "- [ ] Add a leading-indicator alert for this failure class",
    ]
    return "\n".join(lines)


def build_self_diagnosis(state: InvestigationState) -> str:
    """When an investigation fails to verify any root cause, ARGUS turns the
    lens on itself: a deterministic RCA-of-the-RCA from its own execution
    evidence (node errors, unavailable evidence sources, refuted hypotheses).
    The same data is queryable in SigNoz as the argus.investigation trace."""
    lines = [
        "## ARGUS self-diagnosis: why this investigation failed to converge",
        "",
        "_Auto-generated analysis of the investigation's own execution "
        f"(trace `argus.investigation` / `{state.investigation_id}` in SigNoz)._",
        "",
    ]
    unavailable = [e for e in state.evidence if e.unavailable]
    if unavailable:
        lines.append("**Evidence sources that returned nothing:**")
        lines += [f"- {e.source}: {e.summary}" for e in unavailable]
        lines.append("")
    if state.errors:
        lines.append("**Node errors during the run:**")
        lines += [f"- {err}" for err in state.errors]
        lines.append("")
    refuted = [h for h in state.hypotheses if h.verdict == Verdict.refuted]
    errored = [h for h in state.hypotheses if h.verdict == Verdict.error]
    if refuted:
        lines.append("**Hypotheses proposed and struck down (with the disproving query):**")
        lines += [f"- {h.claim} — {h.verdict_detail}" for h in refuted]
        lines.append("")
    if errored:
        lines.append(
            "**Hypotheses that could not be tested (the verification check "
            "itself failed to run — these are untested, not disproven):**"
        )
        lines += [f"- {h.claim} — {h.verdict_detail}" for h in errored]
        lines.append("")
    if errored and not refuted:
        failure_mode = (
            "verification checks failed to run (often a schema mismatch — the "
            "spec references fields this service's telemetry doesn't carry), so "
            "the proposed theories remain untested."
        )
    elif unavailable and not refuted:
        failure_mode = "insufficient evidence reached the hypothesizer (see empty sources above)."
    else:
        failure_mode = (
            "every mechanistically plausible hypothesis was falsified by the "
            "telemetry — the true cause is outside the collected evidence "
            "(consider widening the window or adding infra/change signals)."
        )
    lines.append("**Likely failure mode:** " + failure_mode)
    return "\n".join(lines)


def make(deps: Deps):
    def report(state: InvestigationState) -> InvestigationState:
        confirmed = [h for h in state.hypotheses if h.verdict == Verdict.confirmed]
        refuted = [h for h in state.hypotheses if h.verdict == Verdict.refuted]
        unverified = [h for h in state.hypotheses if h.verdict == Verdict.error]
        degraded = not confirmed

        # Incident-memory citation: a high-similarity past incident is part of
        # the verdict ("we have seen this failure class before").
        from .memory_recall import CITE_SIMILARITY

        memory_evs = [
            e for e in state.available_evidence()
            if e.kind.value == "memory" and e.data.get("similarity", 0) >= CITE_SIMILARITY
        ]
        citation = ""
        if memory_evs:
            top = max(memory_evs, key=lambda e: e.data.get("similarity", 0))
            citation = (
                f" [Incident memory: similar to past incident "
                f"{top.data.get('incident_id')} "
                f"(similarity {top.data.get('similarity', 0):.0%}) — "
                f"see 'Similar past incidents'.]"
            )

        if confirmed:
            best = max(confirmed, key=lambda h: h.confidence)
            root_cause = f"{best.claim} — {best.mechanism} (verified: {best.verdict_detail})"
            root_cause += citation
            confidence = best.confidence
        else:
            root_cause = (
                "No hypothesis survived verification. Evidence-only report; "
                "human investigation required."
            )
            confidence = 0.0

        # Adaptive review bar (see module constants): only a *verified* past
        # incident of the same failure class earns a discount — a degraded or
        # low-confidence memory proves nothing. Never applies to degraded runs.
        effective_threshold = REVIEW_THRESHOLD
        threshold_note = ""
        trusted_memories = [
            e for e in memory_evs
            if not e.data.get("degraded", True)
            and e.data.get("confidence", 0.0) >= REVIEW_THRESHOLD
        ]
        if confirmed and trusted_memories and MEMORY_TRUST_DISCOUNT > 0:
            top_mem = max(trusted_memories, key=lambda e: e.data.get("similarity", 0))
            effective_threshold = max(
                THRESHOLD_FLOOR, REVIEW_THRESHOLD - MEMORY_TRUST_DISCOUNT
            )
            threshold_note = (
                f"adaptive: known failure class — similar to "
                f"{top_mem.data.get('incident_id')} "
                f"(similarity {top_mem.data.get('similarity', 0):.0%}, "
                f"previously verified at {top_mem.data.get('confidence', 0):.0%})"
            )

        metric_evs = [e for e in state.available_evidence() if e.kind.value == "metric"]
        impact = (
            "; ".join(e.summary for e in metric_evs[:3])
            or f"service '{state.service}' alerting: {state.alert.name}"
        )

        elapsed = (datetime.now(timezone.utc) - state.started_at).total_seconds()

        model = state.usage.model or "unknown"
        if "replay" in model:
            llm_label = f"{model} (RECORDED — replayed LLM output, not a live call)"
        elif "heuristic" in model:
            llm_label = f"{model} (DETERMINISTIC — rule-based, no LLM)"
        else:
            llm_label = f"{model} (live)"

        stats = deps.signoz.stats
        rpt = Report(
            title=f"{state.alert.name} — {state.service}",
            root_cause=root_cause,
            confidence=confidence,
            impact=impact,
            timeline=build_timeline(state),
            evidence_bullets=[_evidence_bullet(e) for e in state.available_evidence()],
            refuted=[f"{h.claim} — {h.verdict_detail}" for h in refuted],
            unverified=[f"{h.claim} — {h.verdict_detail}" for h in unverified],
            links=[link for e in state.available_evidence() for link in e.links],
            degraded=degraded,
            needs_review=degraded or confidence < effective_threshold,
            review_threshold=effective_threshold,
            threshold_note=threshold_note,
            llm_label=llm_label,
            query_stats=stats.summary() if stats else "",
        )
        rpt.slack_blocks = build_blocks(state, rpt, elapsed_s=elapsed)
        rpt.postmortem_md = build_postmortem(state, rpt)
        if degraded:
            rpt.postmortem_md += "\n" + build_self_diagnosis(state) + "\n"
        state.report = rpt
        return state

    return report
