#!/usr/bin/env python3
"""Record a live incident into a replayable fixture directory.

Runs a REAL investigation against the live SigNoz (and the configured live
LLM provider), capturing every SigNoz response and LLM completion keyed by
call tag. The result is a fixture that replays offline and doubles as an
eval case.

    uv run python scripts/record_incident.py fixtures/incident-2 \
        --alert scripts/alerts/error-storm.json

After recording, edit <dir>/ground_truth.json to set the expected keywords.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv

from argus.config import Settings
from argus.investigation import run_investigation
from argus.llm import LLMResult, make_provider
from argus.nodes import Deps
from argus.nodes.triage import parse_webhook
from argus.signoz.client import SignozClient
from argus.signoz.links import LinkFactory
from argus.signoz.transport import HttpTransport, QueryStats
from argus.telemetry import setup_telemetry


class RecordingTransport:
    def __init__(self, inner: HttpTransport, out_dir: Path) -> None:
        self._inner = inner
        self._dir = out_dir / "responses"
        self._dir.mkdir(parents=True, exist_ok=True)
        self.stats = QueryStats()

    def query_range(self, payload, tag):
        env = self._inner.query_range(payload, tag)
        self.stats.record(tag, env)
        (self._dir / f"{tag}.json").write_text(json.dumps(env, indent=2))
        return env


class RecordingProvider:
    def __init__(self, inner, out_dir: Path) -> None:
        self._inner = inner
        self._dir = out_dir / "llm"
        self._dir.mkdir(parents=True, exist_ok=True)

    def complete(self, system, user, tag, max_tokens=2000) -> LLMResult:
        result = self._inner.complete(system, user, tag, max_tokens)
        (self._dir / f"{tag}.json").write_text(json.dumps({
            "text": result.text,
            "model": result.model,
            "input_tokens": result.input_tokens,
            "output_tokens": result.output_tokens,
        }, indent=2))
        return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("out_dir")
    ap.add_argument("--alert", required=True, help="alert payload JSON to investigate")
    args = ap.parse_args()

    load_dotenv()
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    settings = Settings.from_env()
    setup_telemetry("")

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    alert_payload = json.loads(Path(args.alert).read_text())
    # 'AUTO' startsAt -> five minutes ago (fresh fault window at record time)
    from datetime import datetime, timedelta, timezone

    for item in alert_payload.get("alerts", []):
        if item.get("startsAt") == "AUTO":
            item["startsAt"] = (
                datetime.now(timezone.utc) - timedelta(minutes=5)
            ).strftime("%Y-%m-%dT%H:%M:%SZ")
    (out / "alert.json").write_text(json.dumps(alert_payload, indent=2))

    transport = RecordingTransport(
        HttpTransport(settings.signoz_url, settings.signoz_api_key), out
    )
    deps = Deps(
        signoz=SignozClient(transport),
        links=LinkFactory(settings.signoz_url),
        llm=RecordingProvider(make_provider(settings), out),
    )
    alert = parse_webhook(alert_payload)
    print(f"recording investigation into {out} (LLM: {settings.resolved_llm_provider()})")
    state = run_investigation(alert, deps, settings.max_verify_iterations,
                              on_node=lambda n, s: print(f"  {n:<22}{s:6.2f}s"))

    # optional-missing manifest: tags that legitimately return empty live
    (out / "optional_missing.json").write_text(json.dumps(
        ["infra.*", "changes.deployments", "traces.search.slow"], indent=2))

    gt_path = out / "ground_truth.json"
    if not gt_path.exists():
        gt_path.write_text(json.dumps({
            "root_cause_keywords": ["EDIT-ME"],
            "expected_service": state.service,
            "min_confirmed_hypotheses": 1,
            "max_cost_usd": 0.50,
        }, indent=2))
    r = state.report
    print("\nrecorded.")
    print("root cause:", r.root_cause if r else None)
    print("verdicts:", [h.verdict.value for h in state.hypotheses])
    print(f"cost: ${state.usage.cost_usd:.4f} · {transport.stats.summary()}")
    print(f"NOW EDIT {gt_path} with real keywords.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
