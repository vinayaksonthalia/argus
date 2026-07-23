"""Self-instrumentation: OTel spans per graph node with gen_ai.* semantic
conventions and token/cost attributes (FR-11).

If OTEL_EXPORTER_OTLP_ENDPOINT is unset the tracer provider has no exporter,
so every span operation is a cheap no-op — replay/demo/tests never need a
collector. When pointed at SigNoz's OTLP endpoint, each investigation shows
up as an `argus.investigation` trace with one child span per node and
`gen_ai.usage.*` attributes on every LLM call.
"""

from __future__ import annotations

import contextlib
from typing import Any, Iterator, Optional

from opentelemetry import metrics, trace
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from .security import scrub_attributes

_initialized = False
_cost_counter = None
_token_counter = None


def setup_telemetry(otlp_endpoint: str = "", service_name: str = "argus") -> None:
    """Idempotent tracer + meter setup. No endpoint -> providers without
    exporters (every span/metric operation is a cheap no-op)."""
    global _initialized
    if _initialized:
        return
    resource = Resource.create({"service.name": service_name})
    provider = TracerProvider(resource=resource)
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
            OTLPSpanExporter,
        )
        endpoint = otlp_endpoint.rstrip("/")
        if not endpoint.endswith("/v1/traces"):
            endpoint = endpoint + "/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
        metrics_endpoint = endpoint[: -len("/v1/traces")] + "/v1/metrics"
        metrics.set_meter_provider(MeterProvider(
            resource=resource,
            metric_readers=[PeriodicExportingMetricReader(
                OTLPMetricExporter(endpoint=metrics_endpoint),
                export_interval_millis=15_000,
            )],
        ))
    trace.set_tracer_provider(provider)
    _initialized = True


def _counters():
    """Lazy meters: `argus.cost.usd` (LLM spend, the meta-alert signal)
    and `argus.tokens` (token burn)."""
    global _cost_counter, _token_counter
    if _cost_counter is None:
        meter = metrics.get_meter("argus")
        _cost_counter = meter.create_counter(
            "argus.cost.usd", unit="USD",
            description="LLM spend per ARGUS investigation step",
        )
        _token_counter = meter.create_counter(
            "argus.tokens", unit="{token}",
            description="LLM tokens consumed by ARGUS",
        )
    return _cost_counter, _token_counter


def tracer() -> trace.Tracer:
    return trace.get_tracer("argus")


@contextlib.contextmanager
def node_span(name: str, attributes: Optional[dict[str, Any]] = None) -> Iterator[trace.Span]:
    """Span per graph node: `argus.node.<name>`; attributes are scrubbed (NFR-6)."""
    with tracer().start_as_current_span(f"argus.node.{name}") as span:
        if attributes:
            for k, v in scrub_attributes(attributes).items():
                span.set_attribute(k, v)
        yield span


@contextlib.contextmanager
def llm_span(
    model: str, operation: str = "chat"
) -> Iterator[trace.Span]:
    """gen_ai.* semantic-convention span for one LLM call. The caller records
    usage via `record_llm_usage` once the response is in."""
    with tracer().start_as_current_span(f"gen_ai.{operation} {model}") as span:
        # current semconv name + legacy alias (SigNoz bundled dashboards use both)
        span.set_attribute("gen_ai.provider.name", "anthropic")
        span.set_attribute("gen_ai.system", "anthropic")
        span.set_attribute("gen_ai.operation.name", operation)
        span.set_attribute("gen_ai.request.model", model)
        yield span


def record_llm_usage(
    span: trace.Span, input_tokens: int, output_tokens: int, cost_usd: float
) -> None:
    span.set_attribute("gen_ai.usage.input_tokens", input_tokens)
    span.set_attribute("gen_ai.usage.output_tokens", output_tokens)
    span.set_attribute("argus.cost.usd", round(cost_usd, 6))
    # The same numbers as OTLP *metrics*, so SigNoz can alert on ARGUS's own
    # spend rate (the `argus.cost.usd` meta-alert pages ARGUS about ARGUS).
    cost_counter, token_counter = _counters()
    cost_counter.add(max(cost_usd, 0.0), {"service.name": "argus"})
    token_counter.add(input_tokens, {"service.name": "argus", "direction": "input"})
    token_counter.add(output_tokens, {"service.name": "argus", "direction": "output"})
