"""ARGUS command line.

    argus investigate --replay fixtures/incident-1   # offline demo, no secrets
    argus eval fixtures/incident-1 [...]             # scorecard over fixtures
    argus serve                                      # live webhook server
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from . import ui
from .config import ConfigError, Settings
from .telemetry import setup_telemetry


def _cmd_investigate(args: argparse.Namespace) -> int:
    from .evals import load_alert, make_replay_deps
    from .investigation import run_investigation
    from .models import Verdict
    from .slack import SlackPoster

    settings = Settings.from_env()
    setup_telemetry(settings.otlp_endpoint)

    if args.replay:
        fixture = Path(args.replay)
        if not (fixture / "alert.json").exists():
            print(f"error: {fixture} is not a fixture directory (no alert.json)", file=sys.stderr)
            return 2
        deps = make_replay_deps(fixture, settings.signoz_url)
        alert = load_alert(fixture)
        if not args.json:
            ui.print_banner("replay investigation (recorded telemetry + recorded LLM)", str(fixture))
    else:
        settings.validate_live()
        from .live import make_live_deps

        if not args.alert:
            print("error: live mode needs --alert <payload.json>", file=sys.stderr)
            return 2
        deps = make_live_deps(settings)
        from .nodes.triage import parse_webhook

        alert = parse_webhook(json.loads(Path(args.alert).read_text()))
        if not args.json:
            ui.print_banner(
                f"live investigation (LLM provider: {settings.resolved_llm_provider()}, "
                f"transport: {settings.transport})",
                settings.signoz_url,
            )

    state = run_investigation(
        alert, deps, settings.max_verify_iterations,
        on_node=None if args.json else ui.node_progress,
    )

    report = state.report
    if report is None:
        ui.print_error("investigation produced no report",
                       why="every node failed before the report step",
                       try_="re-run with --verbose and check SigNoz connectivity")
        return 1

    if args.json:
        # Machine-readable result on stdout (clig.dev); human chrome suppressed.
        print(report.model_dump_json(indent=2, exclude={"postmortem_md", "slack_blocks"}))
    else:
        ui.render_report(state)

    poster = SlackPoster(settings.slack_bot_token, settings.slack_channel)
    posted = poster.post(report.slack_blocks, fallback_text=f"ARGUS RCA: {report.title}")
    print("Slack: posted" if posted else "Slack: dry-run (blocks logged; set SLACK_BOT_TOKEN to post)",
          file=sys.stderr if args.json else sys.stdout)

    out_dir = Path(args.postmortem_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pm_path = out_dir / f"{state.investigation_id}.md"
    pm_path.write_text(report.postmortem_md)
    print(f"Postmortem: {pm_path}", file=sys.stderr if args.json else sys.stdout)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from .evals import format_scorecard, run_eval

    setup_telemetry("")
    if args.providers:
        return _run_provider_benchmark(args)
    results = [run_eval(fixture) for fixture in args.fixtures]
    print(format_scorecard(results))
    return 0 if all(r.passed for r in results) else 1


def _run_provider_benchmark(args: argparse.Namespace) -> int:
    """Run the same recorded incidents through multiple LIVE providers and
    write a comparison report (BYO-API-key deployment guidance)."""
    from .evals import BenchResult, format_benchmark_md, run_provider_case
    from .llm import make_provider

    settings = Settings.from_env()
    providers = [p.strip() for p in args.providers.split(",") if p.strip()]
    results: list[BenchResult] = []
    for name in providers:
        try:
            s = Settings.from_env()
            s.llm_provider = name
            provider = make_provider(s)
        except Exception as exc:  # noqa: BLE001 — missing key/CLI: report, keep going
            for fixture in args.fixtures:
                results.append(BenchResult(provider=name, fixture=fixture,
                                           error=f"provider unavailable: {exc}"))
            continue
        for fixture in args.fixtures:
            ui.console.print(f"[dim]benchmark[/] [bold]{name}[/] × {fixture} …")
            r = run_provider_case(fixture, provider, name)
            status = "ok" if r.keywords_hit else (r.error[:60] or "missed keywords")
            ui.console.print(f"  -> {status} ({r.latency_s:.1f}s, {r.tokens} tok)")
            results.append(r)

    n_runs = 1
    md = format_benchmark_md(
        results,
        runs_note=f"_Run count: n={n_runs} per provider×fixture (single-shot; "
                  "LLM output varies between runs — treat small deltas as noise)._",
    )
    out = Path(args.report)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md)
    ui.console.print(f"\n[bold #3DD68C]benchmark report:[/] {out}")
    print(md)
    return 0


def _cmd_init_dashboards(args: argparse.Namespace) -> int:
    """Create the ARGUS Mission Control dashboard on the live SigNoz."""
    from .signoz.dashboards import DashboardClient, mission_control_dashboard

    settings = Settings.from_env()
    if not settings.signoz_api_key:
        ui.print_error("SIGNOZ_API_KEY is not set", try_="add it to .env")
        return 2
    client = DashboardClient(settings.signoz_url, settings.signoz_api_key)
    url = client.create(mission_control_dashboard())
    ui.console.print(f"[bold #3DD68C]Mission Control dashboard:[/] {url}")
    return 0


def _cmd_memory(args: argparse.Namespace) -> int:
    """Inspect / backfill the incident memory (SQLite + local embeddings)."""
    from .memory import IncidentMemory, IncidentRecord

    settings = Settings.from_env()
    if not settings.memory_enabled():
        ui.print_error("incident memory is disabled (ARGUS_MEMORY_DB=off)")
        return 2
    mem = IncidentMemory(settings.memory_db)

    if args.memory_command == "list":
        records = mem.all()
        if not records:
            ui.console.print("[dim]memory is empty — completed live investigations "
                             "are stored automatically[/]")
            return 0
        for r in records:
            flag = " [degraded]" if r.degraded else ""
            ui.console.print(
                f"[bold]{r.incident_id}[/] {r.occurred_at[:16]} "
                f"service={r.service} alert='{r.alert_name}'{flag}\n"
                f"  root cause: {r.root_cause[:140]}"
            )
        ui.console.print(f"[dim]{len(records)} incidents in {settings.memory_db}[/]")
        return 0

    if args.memory_command == "add-report":
        payload = json.loads(Path(args.report).read_text())
        title = payload.get("title", "")
        alert_name, _, service = title.partition(" — ")
        from datetime import datetime, timezone

        rec = IncidentRecord(
            incident_id=args.id,
            occurred_at=args.occurred_at or datetime.now(timezone.utc).isoformat(),
            alert_name=alert_name or title,
            service=args.service or service or "unknown",
            symptoms="; ".join(payload.get("evidence_bullets", []))[:2000],
            root_cause=payload.get("root_cause", "")[:2000],
            confidence=float(payload.get("confidence", 0.0)),
            degraded=bool(payload.get("degraded", False)),
        )
        mem.store(rec)
        ui.console.print(f"[bold #3DD68C]stored[/] {rec.incident_id} "
                         f"({mem.count()} incidents in memory)")
        return 0

    if args.memory_command == "recall":
        matches = mem.recall(args.query, top_k=3)
        for sim, r in matches:
            ui.console.print(f"{sim:.0%}  [bold]{r.incident_id}[/] ({r.service}) "
                             f"{r.root_cause[:120]}")
        if not matches:
            ui.console.print("[dim]no matches[/]")
        return 0
    return 2


def _cmd_console(args: argparse.Namespace) -> int:
    """Serve the read-only Investigations Console (localhost web UI)."""
    from .console import serve

    settings = Settings.from_env()
    postmortem_dir = Path(args.postmortem_dir)
    memory_db = Path(settings.memory_db) if settings.memory_enabled() else None

    try:
        httpd = serve(postmortem_dir, memory_db, host=args.host, port=args.port)
    except OSError as exc:
        ui.print_error(
            f"could not bind {args.host}:{args.port}",
            why=str(exc),
            try_=f"another process may hold the port — retry with --port {args.port + 1}",
        )
        return 2

    from .console import ConsoleData

    count = ConsoleData(postmortem_dir, memory_db).stats.total
    url = f"http://{args.host}:{args.port}"
    ui.console.print(
        f"[bold #8B5CF6]ARGUS Investigations Console[/] → [bold]{url}[/]\n"
        f"[dim]{count} investigation(s) from {postmortem_dir}/ · read-only · localhost only · Ctrl-C to stop[/]"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        ui.console.print("\n[dim]console stopped[/]")
    finally:
        httpd.server_close()
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from .server import create_app

    settings = Settings.from_env()
    settings.validate_live()
    setup_telemetry(settings.otlp_endpoint)
    app = create_app(settings)
    uvicorn.run(app, host="0.0.0.0", port=settings.listen_port)
    return 0


def _load_env() -> None:
    """Load .env files in an explicit, documented order (NFR-6).

    python-dotenv's default walks up from the *package source file*, which can
    silently pick up an unrelated ancestor `.env`. Instead:

      1. Real environment variables always win (dotenv never overrides them).
      2. `./.env` in the current working directory.
      3. The ARGUS project's own `.env` (next to `pyproject.toml`).
      4. Deliberate fallback: the project's parent directory `.env` — the
         monorepo's shared secrets file (documented in DOCS.md).

    Earlier files win for any variable set in more than one place.
    """
    candidates = [Path.cwd() / ".env"]
    project_root = Path(__file__).resolve().parents[2]
    if (project_root / "pyproject.toml").exists():  # running from a checkout
        candidates.append(project_root / ".env")
        candidates.append(project_root.parent / ".env")
    for env_file in candidates:
        if env_file.is_file():
            load_dotenv(env_file)


_NO_COMMAND_HINT = """\
ARGUS — autonomous AI SRE investigator for SigNoz.

No investigations yet? Try the zero-setup offline demo (no SigNoz, no keys):

    argus investigate --replay fixtures/incident-1

Commands: investigate · eval · serve · console · memory · init-dashboards
Full docs: DOCS.md · learning/ curriculum · argus --help
"""


def main(argv: list[str] | None = None) -> int:
    _load_env()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(prog="argus", description="ARGUS AI SRE investigator for SigNoz")
    sub = parser.add_subparsers(dest="command")

    p_inv = sub.add_parser("investigate", help="run one investigation")
    p_inv.add_argument("--replay", help="fixture directory for offline replay mode")
    p_inv.add_argument("--alert", help="alert payload JSON file (live mode)")
    p_inv.add_argument("--postmortem-dir", default="postmortems")
    p_inv.add_argument("--json", action="store_true",
                       help="emit the report as JSON on stdout (no rich chrome)")
    p_inv.set_defaults(fn=_cmd_investigate)

    p_eval = sub.add_parser("eval", help="score recorded incidents against ground truth")
    p_eval.add_argument("fixtures", nargs="+")
    p_eval.add_argument("--providers",
                        help="comma-separated LIVE providers to benchmark on the same "
                             "fixtures (e.g. claude-cli,groq,cerebras); writes --report")
    p_eval.add_argument("--report", default="evals/PROVIDER-BENCHMARK.md")
    p_eval.set_defaults(fn=_cmd_eval)

    p_serve = sub.add_parser("serve", help="run the webhook server (live mode)")
    p_serve.set_defaults(fn=_cmd_serve)

    p_console = sub.add_parser(
        "console", help="serve the read-only Investigations Console (local web UI)")
    p_console.add_argument("--postmortem-dir", default="postmortems")
    p_console.add_argument("--host", default="127.0.0.1",
                           help="bind address (localhost only by default)")
    p_console.add_argument("--port", type=int, default=7332)
    p_console.set_defaults(fn=_cmd_console)

    p_mem = sub.add_parser("memory", help="inspect / backfill incident memory")
    mem_sub = p_mem.add_subparsers(dest="memory_command", required=True)
    mem_sub.add_parser("list", help="list stored incidents")
    p_mem_add = mem_sub.add_parser("add-report",
                                   help="backfill one incident from a saved report JSON")
    p_mem_add.add_argument("report", help="path to <inv-id>.report.json")
    p_mem_add.add_argument("--id", required=True, help="investigation id (e.g. inv-6bde2d57f9)")
    p_mem_add.add_argument("--occurred-at", default="",
                           help="ISO timestamp of the incident (default: now)")
    p_mem_add.add_argument("--service", default="")
    p_mem_recall = mem_sub.add_parser("recall", help="query the memory")
    p_mem_recall.add_argument("query")
    p_mem.set_defaults(fn=_cmd_memory)

    p_dash = sub.add_parser("init-dashboards",
                            help="create the ARGUS Mission Control dashboard in SigNoz")
    p_dash.set_defaults(fn=_cmd_init_dashboards)

    args = parser.parse_args(argv)
    if args.command is None:
        # Friendly empty state instead of a bare argparse error (design-system
        # CLI rule: pair emptiness with one explanation + one clear action).
        print(_NO_COMMAND_HINT)
        return 2
    try:
        return args.fn(args)
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
