"""Evals harness: replay recorded incidents and score RCA accuracy.

Each fixture directory is one eval case: `alert.json` + recorded SigNoz
responses + recorded LLM outputs + `ground_truth.json`:

    {
      "root_cause_keywords": ["catalog", "db", "pg_sleep"],   # ALL must appear (case-insensitive)
      "expected_service": "catalog",
      "min_confirmed_hypotheses": 1,
      "max_cost_usd": 0.15
    }

The same machinery drives the offline demo (`argus investigate --replay`),
so every recorded incident is automatically an eval case.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from .llm import ReplayProvider
from .models import InvestigationState, Verdict
from .nodes import Deps
from .nodes.triage import parse_webhook
from .signoz.client import SignozClient
from .signoz.links import LinkFactory
from .signoz.transport import ReplayTransport


@dataclass
class EvalResult:
    fixture: str
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    details: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0
    cost_usd: float = 0.0
    tokens: int = 0


def make_replay_deps(fixture_dir: str | Path, signoz_url: str = "http://localhost:8080") -> Deps:
    fixture_dir = Path(fixture_dir)
    transport = ReplayTransport(fixture_dir)
    return Deps(
        signoz=SignozClient(transport),
        links=LinkFactory(signoz_url),
        llm=ReplayProvider(fixture_dir),
    )


def load_alert(fixture_dir: str | Path):
    payload = json.loads((Path(fixture_dir) / "alert.json").read_text())
    return parse_webhook(payload)


def score(state: InvestigationState, ground_truth: dict, fixture: str, elapsed_s: float) -> EvalResult:
    result = EvalResult(
        fixture=fixture,
        passed=False,
        elapsed_s=elapsed_s,
        cost_usd=state.usage.cost_usd,
        tokens=state.usage.input_tokens + state.usage.output_tokens,
    )
    report = state.report
    rca_text = (report.root_cause + " " + " ".join(report.evidence_bullets)).lower() if report else ""

    keywords = [k.lower() for k in ground_truth.get("root_cause_keywords", [])]
    missing = [k for k in keywords if k not in rca_text]
    result.checks["root_cause_keywords"] = not missing
    if missing:
        result.details.append(f"missing keywords in RCA: {missing}")

    expected_service = ground_truth.get("expected_service")
    if expected_service:
        result.checks["service_identified"] = state.service == expected_service
        if state.service != expected_service:
            result.details.append(f"service: got '{state.service}', want '{expected_service}'")

    min_confirmed = int(ground_truth.get("min_confirmed_hypotheses", 1))
    confirmed = sum(1 for h in state.hypotheses if h.verdict == Verdict.confirmed)
    result.checks["hypotheses_confirmed"] = confirmed >= min_confirmed
    if confirmed < min_confirmed:
        result.details.append(f"confirmed hypotheses: {confirmed} < {min_confirmed}")

    result.checks["report_produced"] = report is not None and not report.degraded
    result.checks["links_present"] = bool(report and report.links) and all(
        link.startswith("http") for link in (report.links if report else [])
    )

    max_cost = ground_truth.get("max_cost_usd")
    if max_cost is not None:
        result.checks["cost_within_budget"] = state.usage.cost_usd <= float(max_cost)
        if state.usage.cost_usd > float(max_cost):
            result.details.append(f"cost ${state.usage.cost_usd:.4f} > budget ${max_cost}")

    result.passed = all(result.checks.values())
    return result


def run_eval(fixture_dir: str | Path) -> EvalResult:
    from .investigation import run_investigation

    fixture_dir = Path(fixture_dir)
    ground_truth = json.loads((fixture_dir / "ground_truth.json").read_text())
    deps = make_replay_deps(fixture_dir)
    alert = load_alert(fixture_dir)
    t0 = time.monotonic()
    state = run_investigation(alert, deps)
    return score(state, ground_truth, str(fixture_dir), time.monotonic() - t0)


def format_scorecard(results: list[EvalResult]) -> str:
    lines = ["", "ARGUS eval scorecard", "=" * 60]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"[{status}] {r.fixture}  ({r.elapsed_s:.1f}s, {r.tokens} tok, ${r.cost_usd:.4f})")
        for name, ok in r.checks.items():
            lines.append(f"    {'ok  ' if ok else 'FAIL'} {name}")
        for d in r.details:
            lines.append(f"      -> {d}")
    passed = sum(1 for r in results if r.passed)
    lines += ["=" * 60, f"{passed}/{len(results)} cases passed"]
    return "\n".join(lines)


# ---------------------------------------------------------------- provider benchmark


@dataclass
class BenchResult:
    """One provider × fixture benchmark run (offline replay of recorded
    evidence + a LIVE LLM provider proposing hypotheses)."""

    provider: str
    fixture: str
    ok: bool = False                 # investigation completed with a report
    keywords_hit: bool = False       # ground-truth keywords among proposed root causes
    service_ok: bool = False
    confirmed: int = 0               # informational: offline verification coverage
    hypotheses: int = 0
    latency_s: float = 0.0
    tokens: int = 0
    cost_usd: float = 0.0
    error: str = ""


def run_provider_case(fixture_dir: str | Path, provider, provider_name: str) -> BenchResult:
    """Run one recorded incident's evidence through a live provider.

    SigNoz responses replay from the fixture (lenient: the provider's own
    verification queries, never recorded, return empty). The comparable
    signal is hypothesis quality — did the model propose the true root cause —
    plus latency/tokens/cost.
    """
    from .investigation import run_investigation

    fixture_dir = Path(fixture_dir)
    ground_truth = json.loads((fixture_dir / "ground_truth.json").read_text())
    transport = ReplayTransport(fixture_dir, lenient=True)
    deps = Deps(
        signoz=SignozClient(transport),
        links=LinkFactory("http://localhost:8080"),
        llm=provider,
    )
    result = BenchResult(provider=provider_name, fixture=str(fixture_dir))
    t0 = time.monotonic()
    try:
        state = run_investigation(load_alert(fixture_dir), deps)
    except Exception as exc:  # noqa: BLE001
        result.error = f"{type(exc).__name__}: {exc}"
        result.latency_s = time.monotonic() - t0
        return result
    result.latency_s = time.monotonic() - t0
    result.ok = state.report is not None
    result.tokens = state.usage.input_tokens + state.usage.output_tokens
    result.cost_usd = state.usage.cost_usd
    result.hypotheses = len(state.hypotheses)
    result.confirmed = sum(1 for h in state.hypotheses if h.verdict == Verdict.confirmed)
    if state.errors and not state.hypotheses:
        result.error = "; ".join(state.errors)[:200]

    proposed = " ".join(f"{h.claim} {h.mechanism}" for h in state.hypotheses).lower()
    if state.report:
        proposed += " " + state.report.root_cause.lower()
    keywords = [k.lower() for k in ground_truth.get("root_cause_keywords", [])]
    result.keywords_hit = bool(keywords) and all(k in proposed for k in keywords)
    expected = ground_truth.get("expected_service")
    result.service_ok = (state.service == expected) if expected else True
    return result


def format_benchmark_md(results: list[BenchResult], runs_note: str = "") -> str:
    lines = [
        "# ARGUS provider benchmark",
        "",
        "The SAME recorded incidents (real Faultline telemetry) replayed through",
        "different LIVE LLM providers. Comparable signal = hypothesis quality",
        "(did the model propose the ground-truth root cause), latency, tokens,",
        "cost. **Offline caveat:** verification queries a live model invents were",
        "not recorded, so they replay as empty — 'confirmed' counts here reflect",
        "offline verification coverage, NOT live accuracy; run against live",
        "SigNoz for true verification behavior.",
        "",
        runs_note,
        "",
        "| provider | fixture | root-cause proposed | service id'd | confirmed (offline) | latency | tokens | cost |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.error and not r.hypotheses:
            lines.append(
                f"| {r.provider} | {Path(r.fixture).name} | ERROR: {r.error[:60]} | — | — | "
                f"{r.latency_s:.1f}s | — | — |"
            )
            continue
        lines.append(
            f"| {r.provider} | {Path(r.fixture).name} | "
            f"{'✅' if r.keywords_hit else '❌'} | {'✅' if r.service_ok else '❌'} | "
            f"{r.confirmed}/{r.hypotheses} | {r.latency_s:.1f}s | {r.tokens:,} | "
            f"${r.cost_usd:.4f} |"
        )
    # per-provider summary
    lines += ["", "## Summary", "",
              "| provider | root-cause hit rate | median latency | total tokens | total cost |",
              "|---|---|---|---|---|"]
    import statistics
    by_provider: dict[str, list[BenchResult]] = {}
    for r in results:
        by_provider.setdefault(r.provider, []).append(r)
    for name, rs in by_provider.items():
        scored = [r for r in rs if not (r.error and not r.hypotheses)]
        hits = sum(1 for r in scored if r.keywords_hit)
        lat = statistics.median([r.latency_s for r in rs]) if rs else 0.0
        lines.append(
            f"| {name} | {hits}/{len(scored) if scored else 0} | {lat:.1f}s | "
            f"{sum(r.tokens for r in rs):,} | ${sum(r.cost_usd for r in rs):.4f} |"
        )
    return "\n".join(lines) + "\n"
