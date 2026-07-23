"""Pluggable LLM providers (NFR-9) with per-call token/cost accounting.

Four providers behind one protocol:

- `AnthropicProvider`   — live Claude via the anthropic SDK (needs ANTHROPIC_API_KEY).
- `ClaudeCliProvider`   — live Claude via the locally installed `claude` CLI in
  headless print mode (authenticates with the user's Claude subscription; no
  API key needed). Real tokens/cost are parsed from the CLI's JSON envelope.
- `HeuristicProvider`   — deterministic, rule-based hypothesis generation from
  evidence keywords. Zero tokens, zero cost, no network. Used for live-pipeline
  testing without an LLM; output is clearly labeled "heuristic".
- `ReplayProvider`      — recorded completions from a fixture directory keyed
  by call tag (offline demo, tests, evals) with realistic token/cost numbers.

Select with ARGUS_LLM_PROVIDER=auto|anthropic|claude-cli|heuristic (see config).
"""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .telemetry import llm_span, record_llm_usage

# USD per million tokens (input, output). Approximate public pricing; used for
# the argus.cost.usd metric, not billing.
PRICING_PER_MTOK: dict[str, tuple[float, float]] = {
    "claude-sonnet-4-5": (3.0, 15.0),
    "claude-haiku-4-5": (1.0, 5.0),
    "claude-opus-4-6": (5.0, 25.0),
}
_DEFAULT_PRICE = (3.0, 15.0)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    for prefix, (pin, pout) in PRICING_PER_MTOK.items():
        if model.startswith(prefix):
            return (input_tokens * pin + output_tokens * pout) / 1_000_000
    pin, pout = _DEFAULT_PRICE
    return (input_tokens * pin + output_tokens * pout) / 1_000_000


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd_reported: float | None = None  # provider-reported cost (claude CLI)

    @property
    def cost_usd(self) -> float:
        if self.cost_usd_reported is not None:
            return float(self.cost_usd_reported)
        return estimate_cost_usd(self.model, self.input_tokens, self.output_tokens)


class LLMProvider(Protocol):
    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        """One completion. `tag` names the call for replay lookup and tracing."""
        ...


class AnthropicProvider:
    """Live Claude calls via the anthropic SDK, wrapped in a gen_ai.* span."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-5") -> None:
        import anthropic  # deferred: not needed in replay mode

        self._client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        with llm_span(self.model) as span:
            span.set_attribute("argus.llm.tag", tag)
            msg = self._client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
            )
            text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
            result = LLMResult(
                text=text,
                model=self.model,
                input_tokens=msg.usage.input_tokens,
                output_tokens=msg.usage.output_tokens,
            )
            record_llm_usage(span, result.input_tokens, result.output_tokens, result.cost_usd)
            return result


def make_provider(settings) -> "LLMProvider":
    """Build the live LLM provider from Settings (see config.resolved_llm_provider)."""
    name = settings.resolved_llm_provider()
    if name == "anthropic":
        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    if name == "claude-cli":
        model = settings.anthropic_model
        # CLI prefers aliases; map full ids down to their alias when obvious.
        for alias in ("opus", "sonnet", "haiku"):
            if alias in model:
                model = alias
                break
        return ClaudeCliProvider(model=model)
    if name == "groq":
        return OpenAICompatProvider(
            "https://api.groq.com/openai/v1", settings.groq_api_key,
            settings.groq_model, "groq",
        )
    if name == "cerebras":
        return OpenAICompatProvider(
            "https://api.cerebras.ai/v1", settings.cerebras_api_key,
            settings.cerebras_model, "cerebras",
        )
    if name == "heuristic":
        return HeuristicProvider()
    raise ValueError(
        f"unknown ARGUS_LLM_PROVIDER '{name}' "
        "(expected auto|anthropic|claude-cli|groq|cerebras|heuristic)"
    )


class ClaudeCliError(RuntimeError):
    pass


class ClaudeCliProvider:
    """Live Claude via the local `claude` CLI in headless print mode.

    Uses `claude -p --output-format json --tools "" --system-prompt ...` so the
    call is a single non-interactive completion with no tool use. The CLI's
    JSON envelope carries real token usage and a cost figure, which flow into
    the same accounting as the SDK provider. Requires a logged-in Claude CLI
    (subscription auth) — no ANTHROPIC_API_KEY needed.
    """

    def __init__(self, model: str = "sonnet", timeout_s: float = 240.0,
                 binary: str = "claude") -> None:
        resolved = shutil.which(binary)
        if not resolved:
            raise ClaudeCliError(
                f"'{binary}' CLI not found on PATH — install Claude Code or use "
                "another provider (ARGUS_LLM_PROVIDER)."
            )
        self._bin = resolved
        self.model = model
        self._timeout = timeout_s

    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        with llm_span(self.model) as span:
            span.set_attribute("argus.llm.tag", tag)
            span.set_attribute("argus.llm.provider", "claude-cli")
            cmd = [
                self._bin, "-p", "--output-format", "json",
                "--model", self.model,
                "--tools", "",
                "--system-prompt", system,
                "--max-turns", "1",
            ]
            try:
                proc = subprocess.run(
                    cmd, input=user, capture_output=True, text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise ClaudeCliError(f"claude CLI timed out after {self._timeout}s") from exc
            if proc.returncode != 0:
                raise ClaudeCliError(
                    f"claude CLI exited {proc.returncode}: {proc.stderr.strip()[:500]}"
                )
            try:
                envelope = json.loads(proc.stdout)
            except json.JSONDecodeError as exc:
                raise ClaudeCliError(
                    f"claude CLI returned non-JSON output: {proc.stdout[:200]!r}"
                ) from exc
            if envelope.get("is_error"):
                raise ClaudeCliError(f"claude CLI error result: {envelope.get('result', '')[:500]}")
            usage = envelope.get("usage") or {}
            # Resolve the concrete model id when reported (modelUsage keys).
            model_id = next(iter(envelope.get("modelUsage") or {}), self.model)
            result = LLMResult(
                text=str(envelope.get("result", "")),
                model=model_id,
                input_tokens=int(usage.get("input_tokens", 0))
                + int(usage.get("cache_read_input_tokens", 0))
                + int(usage.get("cache_creation_input_tokens", 0)),
                output_tokens=int(usage.get("output_tokens", 0)),
                cost_usd_reported=envelope.get("total_cost_usd"),
            )
            record_llm_usage(span, result.input_tokens, result.output_tokens, result.cost_usd)
            return result


class OpenAICompatProvider:
    """Any OpenAI-compatible chat-completions endpoint (Groq, Cerebras, …).

    Free-tier fallback for demo resilience: real tokens are recorded from the
    response `usage`; cost is $0.00 (free tier) and the provider name is
    carried into the RCA footer label.
    """

    def __init__(self, base_url: str, api_key: str, model: str, provider_name: str,
                 timeout_s: float = 120.0) -> None:
        if not api_key:
            raise ValueError(f"{provider_name}: no API key configured")
        self._base = base_url.rstrip("/")
        self._key = api_key
        self.model = model
        self.provider_name = provider_name
        self._timeout = timeout_s

    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        import httpx

        with llm_span(self.model) as span:
            span.set_attribute("argus.llm.tag", tag)
            span.set_attribute("argus.llm.provider", self.provider_name)
            resp = httpx.post(
                f"{self._base}/chat/completions",
                headers={"Authorization": f"Bearer {self._key}"},
                json={
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            body = resp.json()
            usage = body.get("usage") or {}
            result = LLMResult(
                text=str(body["choices"][0]["message"]["content"]),
                model=f"{self.provider_name}:{body.get('model', self.model)}",
                input_tokens=int(usage.get("prompt_tokens", 0)),
                output_tokens=int(usage.get("completion_tokens", 0)),
                cost_usd_reported=0.0,  # free tier
            )
            record_llm_usage(span, result.input_tokens, result.output_tokens, result.cost_usd)
            return result


class HeuristicProvider:
    """Deterministic rule-based fallback: derives falsifiable hypotheses from
    evidence keywords, no LLM at all. Exists so the live pipeline (webhook →
    evidence → verify → report) can be exercised end-to-end without network or
    tokens. Output is labeled 'heuristic-v1' everywhere it surfaces.
    """

    model = "heuristic-v1"

    _RULES: list[tuple[tuple[str, ...], dict]] = [
        (
            ("pg_sleep", "db.statement", "select", "postgres", "slow"),
            {
                "claim": "A database query in {service} became pathologically slow",
                "mechanism": "a slow SQL statement (visible in the deepest erroring/longest span) "
                             "stalls request handling and inflates p99 latency upstream",
                "confidence": 0.7,
                "verification": {
                    "kind": "query_range",
                    "params": {"signal": "traces", "aggregation": "p99(duration_nano)",
                               "filter_expression": "service.name = '{service}'"},
                    "expected": {"op": "ratio_gt", "value": 2,
                                 "description": "p99 latency at least doubled vs the prior hour"},
                },
            },
        ),
        (
            ("error", "5xx", "502", "500", "exception", "fatal"),
            {
                "claim": "{service} is throwing a storm of server errors",
                "mechanism": "a downstream dependency or code path is failing, surfacing as "
                             "errored spans and ERROR/FATAL logs",
                "confidence": 0.6,
                "verification": {
                    "kind": "query_range",
                    "params": {"signal": "traces", "aggregation": "count()",
                               "filter_expression": "service.name = '{service}' AND has_error = true"},
                    "expected": {"op": "ratio_gt", "value": 2,
                                 "description": "errored span count at least doubled vs prior hour"},
                },
            },
        ),
        (
            ("deploy", "deployment", "version", "rollout"),
            {
                "claim": "A recent deployment to {service} regressed it",
                "mechanism": "a change event in the window correlates with the symptom onset",
                "confidence": 0.5,
                "verification": {
                    "kind": "log_check",
                    "params": {"signal": "logs",
                               "filter_expression": "service.name = '{service}'"},
                    "expected": {"op": "contains", "value": "deploy",
                                 "description": "a deployment event log exists in the window"},
                },
            },
        ),
    ]

    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        low = user.lower()
        # crude service extraction from the standard prompt phrasing
        service = "unknown"
        marker = "for service '"
        if marker in user:
            service = user.split(marker, 1)[1].split("'", 1)[0]
        hypotheses = []
        for keywords, template in self._RULES:
            if any(k in low for k in keywords):
                h = json.loads(json.dumps(template))  # deep copy
                h["claim"] = h["claim"].format(service=service)
                h["mechanism"] = h["mechanism"].format(service=service)
                fe = h["verification"]["params"].get("filter_expression", "")
                h["verification"]["params"]["filter_expression"] = fe.format(service=service)
                hypotheses.append(h)
            if len(hypotheses) == 4:
                break
        if not hypotheses:
            hypotheses = [{
                "claim": f"Service {service} degraded for an undetermined reason",
                "mechanism": "insufficient keyword evidence; verifying a latency regression",
                "confidence": 0.3,
                "verification": {
                    "kind": "query_range",
                    "params": {"signal": "traces", "aggregation": "p99(duration_nano)",
                               "filter_expression": f"service.name = '{service}'"},
                    "expected": {"op": "ratio_gt", "value": 1.5,
                                 "description": "p99 latency regressed vs prior hour"},
                },
            }]
        text = json.dumps(hypotheses[:4])
        result = LLMResult(text=text, model=self.model, input_tokens=0, output_tokens=0)
        with llm_span(self.model) as span:
            span.set_attribute("argus.llm.tag", tag)
            span.set_attribute("argus.llm.provider", "heuristic")
            record_llm_usage(span, 0, 0, 0.0)
        return result


class ReplayProvider:
    """Serves recorded completions from `<fixture_dir>/llm/<tag>.json`.

    File format: {"text": "...", "model": "...", "input_tokens": N, "output_tokens": N}
    Emits the same gen_ai.* spans as the live provider so self-observation and
    cost tracking are exercised offline too.
    """

    def __init__(self, fixture_dir: str | Path) -> None:
        self._dir = Path(fixture_dir) / "llm"

    def complete(self, system: str, user: str, tag: str, max_tokens: int = 2000) -> LLMResult:
        path = self._dir / f"{tag}.json"
        if not path.exists():
            raise FileNotFoundError(
                f"replay fixture missing LLM response for tag '{tag}' ({path})"
            )
        payload = json.loads(path.read_text())
        recorded_model = payload.get("model", "unknown")
        result = LLMResult(
            text=payload["text"],
            # 'replay:' prefix flows into every output label so a recorded run
            # can never masquerade as a live LLM call.
            model=f"replay:{recorded_model}",
            input_tokens=int(payload.get("input_tokens", 0)),
            output_tokens=int(payload.get("output_tokens", 0)),
        )
        with llm_span(result.model) as span:
            span.set_attribute("argus.llm.tag", tag)
            span.set_attribute("argus.llm.replay", True)
            record_llm_usage(span, result.input_tokens, result.output_tokens, result.cost_usd)
        return result
