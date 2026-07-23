"""Typed domain models shared by every graph node.

Everything the investigation touches — the parsed alert, collected evidence,
hypotheses with their falsifiable verification specs, and the final report —
is a pydantic model so nodes have a compile-time-ish contract and the state
serializes cleanly for replay/eval fixtures.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------- alert


class Alert(BaseModel):
    """One alert item from an Alertmanager-compatible webhook payload."""

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    starts_at: Optional[datetime] = None
    fingerprint: Optional[str] = None

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "unknown-alert")

    @property
    def service(self) -> Optional[str]:
        for key in ("service.name", "service_name", "service", "serviceName"):
            if key in self.labels:
                return self.labels[key]
        return None


class TimeWindow(BaseModel):
    """A [start, end) window in UTC. Provides ms epoch accessors for query payloads."""

    start: datetime
    end: datetime

    @property
    def start_ms(self) -> int:
        return int(self.start.timestamp() * 1000)

    @property
    def end_ms(self) -> int:
        return int(self.end.timestamp() * 1000)

    def before_window(self, minutes: int = 60) -> "TimeWindow":
        """The comparison window immediately preceding this one."""
        return TimeWindow(start=self.start - timedelta(minutes=minutes), end=self.start)


# ---------------------------------------------------------------- evidence


class EvidenceKind(str, Enum):
    metric = "metric"
    trace = "trace"
    log = "log"
    infra = "infra"
    change = "change"
    memory = "memory"


class Evidence(BaseModel):
    """One unit of collected evidence. `summary` is human/LLM-facing prose;
    `data` carries structured details; `links` are SigNoz deep links backing it."""

    kind: EvidenceKind
    source: str  # which node / query produced it, e.g. "golden_signals.p99"
    summary: str
    data: dict[str, Any] = Field(default_factory=dict)
    links: list[str] = Field(default_factory=list)
    unavailable: bool = False  # graceful-degradation marker (NFR-4)


class SpanInfo(BaseModel):
    span_id: str = ""
    parent_span_id: str = ""
    trace_id: str = ""
    name: str = ""
    service: str = ""
    duration_ms: float = 0.0
    has_error: bool = False
    attributes: dict[str, str] = Field(default_factory=dict)
    events: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------- hypotheses


class VerificationKind(str, Enum):
    query_range = "query_range"
    trace_check = "trace_check"
    log_check = "log_check"


class Expected(BaseModel):
    """Falsifiable expectation evaluated mechanically by the verify node."""

    op: Literal["gt", "lt", "ratio_gt", "contains"]
    value: float | str
    description: str = ""


class VerificationSpec(BaseModel):
    """Machine-runnable check for a hypothesis (FR-6). `params` is whitelisted
    per kind by the verify node; the model cannot invent side effects."""

    kind: VerificationKind
    params: dict[str, Any] = Field(default_factory=dict)
    expected: Expected


class Verdict(str, Enum):
    pending = "pending"
    confirmed = "confirmed"
    refuted = "refuted"
    error = "error"


class Hypothesis(BaseModel):
    claim: str
    mechanism: str
    confidence: float = Field(ge=0.0, le=1.0)
    verification: VerificationSpec
    verdict: Verdict = Verdict.pending
    verdict_detail: str = ""

    @field_validator("claim", "mechanism")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v


# ---------------------------------------------------------------- usage / cost


class UsageTotals(BaseModel):
    """Token/cost accumulator per investigation (LLM cost tracing)."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    llm_calls: int = 0
    model: str = ""  # last model/provider used, for output labeling

    def add(self, input_tokens: int, output_tokens: int, cost_usd: float, model: str = "") -> None:
        self.input_tokens += input_tokens
        self.output_tokens += output_tokens
        self.cost_usd += cost_usd
        self.llm_calls += 1
        if model:
            self.model = model


# ---------------------------------------------------------------- report / state


class Report(BaseModel):
    title: str
    root_cause: str
    confidence: float
    impact: str
    timeline: list[str] = Field(default_factory=list)
    evidence_bullets: list[str] = Field(default_factory=list)
    refuted: list[str] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)
    slack_blocks: list[dict[str, Any]] = Field(default_factory=list)
    postmortem_md: str = ""
    degraded: bool = False  # evidence-only report (no verified hypothesis)
    needs_review: bool = False  # confidence below the human-review threshold
    llm_label: str = ""  # which LLM/provider produced the hypotheses (honesty label)
    query_stats: str = ""  # ARGUS's own read footprint (rowsScanned etc.)


class InvestigationState(BaseModel):
    """The single state object threaded through every graph node."""

    investigation_id: str
    alert: Alert
    service: str = "unknown"
    window: Optional[TimeWindow] = None
    fingerprint: str = ""
    evidence: list[Evidence] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 2
    usage: UsageTotals = Field(default_factory=UsageTotals)
    report: Optional[Report] = None
    errors: list[str] = Field(default_factory=list)
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def add_evidence(self, ev: Evidence) -> None:
        self.evidence.append(ev)

    def available_evidence(self) -> list[Evidence]:
        return [e for e in self.evidence if not e.unavailable]


def dedup_fingerprint(alert: Alert, window: TimeWindow, round_minutes: int = 5) -> str:
    """Stable dedup key: alert identity + window rounded to `round_minutes` (NFR-3)."""
    bucket = int(window.start.timestamp() // (round_minutes * 60))
    raw = f"{alert.name}|{alert.service or ''}|{alert.fingerprint or ''}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]
