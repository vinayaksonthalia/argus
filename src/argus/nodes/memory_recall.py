"""Memory-recall node (FR-14): before hypothesizing, retrieve the top-3 most
similar past incidents from the local incident memory and inject them as
evidence. High-similarity matches ("same failure class seen before") are
cited in the final RCA by the report node.

Graceful degradation: no memory configured, or an empty corpus, adds an
explicit 'unavailable' marker and the investigation proceeds unchanged."""

from __future__ import annotations

import logging

from ..models import Evidence, EvidenceKind, InvestigationState
from . import Deps

logger = logging.getLogger("argus.memory")

RECALL_MIN_SIMILARITY = 0.20  # below this a match is noise, not a memory
CITE_SIMILARITY = 0.55  # at/above this the RCA cites the past incident


def build_query_text(state: InvestigationState) -> str:
    """The current incident's signature-so-far: alert + service + symptoms."""
    symptoms = "; ".join(
        e.summary for e in state.available_evidence() if e.kind != EvidenceKind.memory
    )
    return " ".join((state.alert.name, state.service, symptoms))


def make(deps: Deps):
    def memory_recall(state: InvestigationState) -> InvestigationState:
        if deps.memory is None:
            state.add_evidence(Evidence(
                kind=EvidenceKind.memory, source="memory.recall",
                summary="incident memory not configured", unavailable=True,
            ))
            return state
        matches = deps.memory.recall(
            build_query_text(state),
            top_k=3,
            exclude_id=state.investigation_id,
            min_similarity=RECALL_MIN_SIMILARITY,
        )
        if not matches:
            state.add_evidence(Evidence(
                kind=EvidenceKind.memory, source="memory.recall",
                summary=f"no similar past incidents in memory "
                        f"({deps.memory.count()} stored)", unavailable=True,
            ))
            return state
        for sim, rec in matches:
            outcome = "root cause was" if not rec.degraded else \
                "investigation did not converge; evidence pointed to"
            state.add_evidence(Evidence(
                kind=EvidenceKind.memory,
                source="memory.recall",
                summary=(
                    f"similar to incident {rec.incident_id} ({rec.occurred_date()}, "
                    f"alert '{rec.alert_name}', service {rec.service}, "
                    f"similarity {sim:.0%}): {outcome}: {rec.root_cause[:400]}"
                ),
                data={
                    "incident_id": rec.incident_id,
                    "similarity": round(sim, 4),
                    "occurred_at": rec.occurred_at,
                    "service": rec.service,
                    "confidence": rec.confidence,
                },
            ))
            logger.info(
                "memory recall: %s similarity %.2f", rec.incident_id, sim
            )
        return state

    return memory_recall
