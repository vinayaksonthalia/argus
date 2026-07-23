"""Change-correlation node (P1, FR-10): recent deploy events across services,
read from structured OTel logs with `event.name = 'deployment'`.

The filter uses the context-qualified form `attribute.event.name`: the bare
key `event.name` makes SigNoz's expression parser hard-error with 400
("key `name` not found") whenever no deployment event has ever been ingested,
while the qualified form parses cleanly and just returns zero rows. This bug
was discovered by ARGUS itself — the spend meta-investigation
(inv-a2a0b2e215) walked ARGUS's own spans in SigNoz and root-caused the
recurring erroring `signoz.query_range.changes.deployments` span. See
assets/live-meta-alert-argus-pages-itself.txt."""

from __future__ import annotations

from ..models import Evidence, EvidenceKind, InvestigationState
from ..security import cap_line
from . import Deps

DEPLOYMENT_FILTER = "attribute.event.name = 'deployment'"


def make(deps: Deps):
    def change_corr(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        try:
            rows = deps.signoz.search_logs(
                DEPLOYMENT_FILTER, state.window, tag="changes.deployments"
            )
        except Exception:  # noqa: BLE001 — degrade gracefully on any query error
            rows = []
        if not rows:
            state.add_evidence(Evidence(
                kind=EvidenceKind.change, source="change_corr",
                summary="no deployments recorded in the alert window",
                unavailable=True,
            ))
            return state
        for row in rows[:5]:
            svc = row.get("service.name", row.get("service_name", "?"))
            version = row.get("service.version", row.get("service_version", "?"))
            body = cap_line(str(row.get("body", "")), 200)
            state.add_evidence(Evidence(
                kind=EvidenceKind.change,
                source="change_corr.deployment",
                summary=f"deployment: service={svc} version={version} — {body}",
                data={"service": str(svc), "version": str(version)},
                links=[deps.links.logs_explorer(DEPLOYMENT_FILTER, state.window)],
            ))
        return state

    return change_corr
