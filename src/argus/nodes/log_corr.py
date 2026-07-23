"""Log-correlation node: logs by exemplar trace_id + ERROR/FATAL for the
service, clustered into templates; novel signatures vs the prior hour (FR-5).

Template clustering is deliberately simple (drain-lite): digits, hex ids and
uuids are replaced with `<*>` so "payment 4812 failed" and "payment 9931
failed" cluster together. Every line is length-capped before it can ever
reach the model (NFR-7).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Iterable

from ..models import Evidence, EvidenceKind, InvestigationState
from ..security import cap_line
from . import Deps

_NUM_RE = re.compile(r"\b\d+(\.\d+)?\b")
_HEX_RE = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)


def template_of(line: str) -> str:
    t = _UUID_RE.sub("<*>", line)
    t = _HEX_RE.sub("<*>", t)
    t = _NUM_RE.sub("<*>", t)
    return cap_line(t.strip(), 300)


def cluster(bodies: Iterable[str]) -> Counter:
    return Counter(template_of(b) for b in bodies if b.strip())


def _bodies(rows: list[dict[str, Any]]) -> list[str]:
    return [str(r.get("body", r.get("message", ""))) for r in rows]


def make(deps: Deps):
    def log_corr(state: InvestigationState) -> InvestigationState:
        assert state.window is not None
        service = state.service
        expr = f"service.name = '{service}' AND severity_text IN ('ERROR','FATAL')"

        current = deps.signoz.search_logs(expr, state.window, tag="logs.errors.current")
        prior = deps.signoz.search_logs(
            expr, state.window.before_window(60), tag="logs.errors.prior"
        )

        trace_rows: list[dict[str, Any]] = []
        trace_ids = [
            e.data.get("trace_id")
            for e in state.evidence
            if e.kind == EvidenceKind.trace and e.data.get("trace_id")
        ][:3]
        for i, tid in enumerate(trace_ids):
            trace_rows += deps.signoz.search_logs(
                f"trace_id = '{tid}'", state.window, tag=f"logs.trace.{i}"
            )

        if not current and not trace_rows:
            state.add_evidence(Evidence(
                kind=EvidenceKind.log, source="log_corr",
                summary="no error logs found for the service in the alert window",
                unavailable=True,
            ))
            return state

        current_clusters = cluster(_bodies(current) + _bodies(trace_rows))
        prior_templates = set(cluster(_bodies(prior)).keys())
        novel = [(t, c) for t, c in current_clusters.most_common() if t not in prior_templates]
        top = novel[:3] if novel else current_clusters.most_common(3)
        novelty = "novel vs prior hour" if novel else "pre-existing"

        for template, count in top:
            state.add_evidence(Evidence(
                kind=EvidenceKind.log,
                source="log_corr.signature",
                summary=f"log signature x{count} ({novelty}): {template}",
                data={"template": template, "count": count, "novel": bool(novel)},
                links=[deps.links.logs_explorer(expr, state.window)],
            ))
        return state

    return log_corr
