"""Investigation graph nodes. Each module exposes `make(deps) -> NodeFn`."""

from __future__ import annotations

from dataclasses import dataclass

from ..llm import LLMProvider
from ..signoz.client import SignozClient
from ..signoz.links import LinkFactory


@dataclass
class Deps:
    """Dependencies injected into every node factory."""

    signoz: SignozClient
    links: LinkFactory
    llm: LLMProvider
    dashboards: object | None = None  # DashboardClient in live mode; None offline
    memory: object | None = None  # IncidentMemory; None disables recall/store
    rules: object | None = None  # RuleClient in live mode; None disables draft rules


# Imported after Deps so node modules can `from . import Deps`.
from . import (  # noqa: E402
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

__all__ = [
    "Deps", "act", "change_corr", "golden_signals", "hypothesize", "infra",
    "log_corr", "memory_recall", "report", "trace_dive", "triage", "verify",
]
