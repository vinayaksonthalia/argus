"""Act node (P2, FR-13/FR-15): after the RCA is assembled,

1. create the per-incident evidence dashboard via POST /api/v1/dashboards;
2. on a CONFIRMED root cause, propose a DRAFT follow-up alert rule via
   POST /api/v2/rules — the leading indicator for this failure class,
   created `disabled: true` and named `[DRAFT · ARGUS]`. **Never enabled
   automatically**: a human reviews the threshold and flips it on.

Read-mostly by design: ARGUS only *adds* resources, never mutates or deletes
existing alerting. Replay/offline runs (no clients configured) skip cleanly."""

from __future__ import annotations

import logging

from ..models import InvestigationState, Verdict
from ..signoz.dashboards import incident_dashboard
from . import Deps

logger = logging.getLogger("argus.act")


def _draft_followup_rule(deps: Deps, state: InvestigationState) -> None:
    from ..signoz.rules import draft_rule_from_hypothesis

    report = state.report
    confirmed = [h for h in state.hypotheses if h.verdict == Verdict.confirmed]
    if not confirmed or report is None:
        return
    best = max(confirmed, key=lambda h: h.confidence)
    spec_params = {
        **best.verification.params,
        "op": best.verification.expected.op,
        "expected_value": best.verification.expected.value,
    }
    import os

    rule = draft_rule_from_hypothesis(
        service=state.service,
        investigation_id=state.investigation_id,
        alert_name=state.alert.name,
        claim=best.claim,
        spec_params=spec_params,
        # SigNoz requires >=1 channel even on disabled rules; the draft stays
        # disabled so nothing fires until a human reviews and enables it.
        channels=[os.getenv("ARGUS_DRAFT_RULE_CHANNEL", "argus-webhook")],
    )
    if rule is None:
        logger.info("confirmed hypothesis has no threshold-rule mapping; no draft rule")
        return
    rule_id = deps.rules.create(rule)
    url = deps.rules.rule_url(rule_id)
    report.evidence_bullets.append(
        f"DRAFT follow-up alert rule proposed (disabled — review & enable): {url}"
    )
    report.links.append(url)
    report.postmortem_md += (
        f"\n## Draft follow-up alert (leading indicator)\n"
        f"- `{rule['alert']}` — created **disabled**; review and enable: {url}\n"
    )
    logger.info("draft follow-up rule created: %s (%s)", rule["alert"], rule_id)


def make(deps: Deps):
    def act(state: InvestigationState) -> InvestigationState:
        report = state.report
        if report is None:
            return state
        if deps.dashboards is not None:
            dashboard = incident_dashboard(
                state.service, state.investigation_id, state.alert.name
            )
            url = deps.dashboards.create(dashboard)
            report.links.insert(0, url)
            report.evidence_bullets.append(f"incident evidence dashboard auto-created: {url}")
            report.postmortem_md += f"\n## Evidence dashboard\n- {url}\n"
            logger.info("incident dashboard created: %s", url)
        if deps.rules is not None:
            _draft_followup_rule(deps, state)
        return state

    return act
