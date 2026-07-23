"""Infra node (P1, FR-9): container/pod memory + restart signals for the
service. Degrades to an explicit 'unavailable' evidence marker when infra
metrics are absent (common in fixture/demo setups) — never fails the graph."""

from __future__ import annotations

from ..models import Evidence, EvidenceKind, InvestigationState, TimeWindow
from ..signoz.queries import builder_payload, mean, series_values
from . import Deps


def _metric_spec(metric: str, service: str) -> dict:
    # Metrics use OBJECT aggregations (metricName/timeAggregation/spaceAggregation),
    # not expression strings — verified in research/signals-playbook.md §1.2.
    return {
        "name": "A",
        "signal": "metrics",
        "aggregations": [{
            "metricName": metric,
            "timeAggregation": "avg",
            "spaceAggregation": "avg",
        }],
        "filter": {"expression": f"k8s.pod.name CONTAINS '{service}'"},
        "stepInterval": 60,
        "disabled": False,
    }


def make(deps: Deps):
    def infra(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        window: TimeWindow = state.window
        found = False
        checks = (
            ("k8s.container.memory.usage", "container memory (bytes)"),
            ("k8s.container.cpu.usage", "container CPU"),
            ("k8s.container.restarts", "container restarts"),
        )
        transport = deps.signoz._t  # transport seam; tags keep this replayable
        for metric, label in checks:
            tag = f"infra.{metric.replace('.', '_')}"
            try:
                env = transport.query_range(
                    builder_payload(window, [_metric_spec(metric, state.service)]), tag
                )
            except Exception:  # noqa: BLE001 — absent infra metrics 400 on some setups
                continue
            values = series_values(env)
            if not values:
                continue
            found = True
            before = mean([v for v in values if v[0] < window.start_ms + 60000])
            after = mean(values)
            state.add_evidence(Evidence(
                kind=EvidenceKind.infra,
                source=f"infra.{metric}",
                summary=f"{label}: mean {after:,.0f} over window (early sample {before:,.0f})",
                data={"metric": metric, "mean": after},
            ))
        if not found:
            state.add_evidence(Evidence(
                kind=EvidenceKind.infra, source="infra",
                summary="infrastructure metrics unavailable for this service",
                unavailable=True,
            ))
        return state

    return infra
