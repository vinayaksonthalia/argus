"""Rich terminal output for ARGUS, per the shared design system.

Tokens mirrored from research/design-system.md so hex values never drift
between the CLI, Slack, and dashboards:
  severity: critical #E5484D · warning #F5A623 · healthy #3DD68C ·
            info #5B8DEF · unknown #6C6D75
  ARGUS accent: violet #8B5CF6

Rules honored: human output by default with --plain/--json degradation
(rich already respects NO_COLOR and non-TTY pipes); severity colors are
semantic and identical to the Slack surface; numeric columns right-aligned;
errors rewritten as What/Why/Try to stderr.
"""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .models import InvestigationState, Verdict

SEV = {
    "critical": "#E5484D",
    "error": "#E5484D",
    "warning": "#F5A623",
    "healthy": "#3DD68C",
    "info": "#5B8DEF",
    "unknown": "#6C6D75",
}
ACCENT = "#8B5CF6"

console = Console()
err_console = Console(stderr=True)


def print_banner(mode: str, source: str) -> None:
    console.print(
        Panel.fit(
            f"[bold {ACCENT}]ARGUS[/] — autonomous SRE investigator\n"
            f"[dim]{mode} · {source}[/]",
            border_style=ACCENT,
        )
    )


def node_progress(name: str, seconds: float) -> None:
    console.print(f"  [dim]·[/] [{ACCENT}]{name:<22}[/] [dim]{seconds:6.2f}s[/]")


def print_error(what: str, why: str = "", try_: str = "") -> None:
    err_console.print(f"[bold {SEV['critical']}]Error:[/] {what}")
    if why:
        err_console.print(f"[dim]Why: {why}[/]")
    if try_:
        err_console.print(f"Try: {try_}")


def render_report(state: InvestigationState) -> None:
    report = state.report
    assert report is not None

    if report.needs_review:
        verdict_txt = Text("NEEDS HUMAN REVIEW", style=f"bold {SEV['warning']}")
    else:
        verdict_txt = Text("ROOT CAUSE VERIFIED", style=f"bold {SEV['healthy']}")

    header = Text.assemble(
        verdict_txt, ("  ·  confidence ", "dim"),
        (f"{report.confidence:.0%}", "bold"),
    )
    console.print()
    console.print(Panel(header, title=f"RCA — {report.title}", border_style=ACCENT))

    console.print(Panel(report.root_cause, title="Root cause",
                        border_style=SEV["healthy"] if not report.degraded else SEV["warning"]))

    hyp = Table(title="Hypotheses", title_justify="left", border_style="dim",
                show_edge=False, pad_edge=False)
    hyp.add_column("Verdict", no_wrap=True)
    hyp.add_column("Claim")
    hyp.add_column("Confidence", justify="right")
    hyp.add_column("Verification detail")
    for h in state.hypotheses:
        color = {
            Verdict.confirmed: SEV["healthy"],
            Verdict.refuted: SEV["critical"],
            Verdict.error: SEV["warning"],
            Verdict.pending: SEV["unknown"],
        }[h.verdict]
        hyp.add_row(
            Text(h.verdict.value.upper(), style=f"bold {color}"),
            h.claim, f"{h.confidence:.0%}", Text(h.verdict_detail, style="dim"),
        )
    console.print(hyp)

    if report.timeline:
        tl = Table(show_header=False, border_style="dim", show_edge=False, pad_edge=False,
                   title="Timeline", title_justify="left")
        tl.add_column("", style="dim")
        for entry in report.timeline:
            tl.add_row(f"• {entry}")
        console.print(tl)

    if report.evidence_bullets:
        ev = Table(show_header=False, border_style="dim", show_edge=False, pad_edge=False,
                   title="Evidence (each claim deep-links into SigNoz)", title_justify="left")
        ev.add_column("")
        for bullet in report.evidence_bullets[:10]:
            ev.add_row(f"• {bullet}")
        console.print(ev)

    footer = (
        f"[dim]LLM: {report.llm_label} · {state.usage.llm_calls} calls · "
        f"{state.usage.input_tokens}+{state.usage.output_tokens} tokens · "
        f"est. ${state.usage.cost_usd:.4f}"
        + (f" · {report.query_stats}" if report.query_stats else "")
        + "[/]"
    )
    console.print(footer)
    if state.errors:
        console.print(f"[{SEV['warning']}]Degradation notes:[/] [dim]{'; '.join(state.errors)}[/]")
