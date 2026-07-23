"""Verify node (FR-7): mechanically execute each hypothesis's verification
spec against SigNoz and mark it confirmed/refuted. No LLM involved — this is
the injection firewall: claims without telemetry backing die here."""

from __future__ import annotations

from ..models import InvestigationState, Verdict
from . import Deps


def make(deps: Deps):
    def verify(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        pending = [h for h in state.hypotheses if h.verdict == Verdict.pending]
        for i, hypothesis in enumerate(pending):
            tag = f"verify.{state.iteration}.{i}"
            try:
                passed, detail = deps.signoz.run_verification(
                    hypothesis.verification, state.window, tag
                )
                hypothesis.verdict = Verdict.confirmed if passed else Verdict.refuted
                hypothesis.verdict_detail = detail
            except Exception as exc:  # noqa: BLE001 — one bad spec must not kill the loop
                hypothesis.verdict = Verdict.error
                hypothesis.verdict_detail = f"verification failed to run: {exc}"
                state.errors.append(f"verify[{tag}]: {exc}")
        return state

    return verify


def route_after_verify(state: InvestigationState) -> str:
    """confirmed -> report; all refuted and budget left -> hypothesize again;
    otherwise -> report (degraded, evidence-only)."""
    if any(h.verdict == Verdict.confirmed for h in state.hypotheses):
        return "report"
    if state.iteration < state.max_iterations:
        return "hypothesize"
    return "report"
