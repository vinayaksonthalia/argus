"""Slack Block Kit RCA builder and poster.

Without a SLACK_BOT_TOKEN the poster runs in dry-run mode and pretty-prints
the blocks JSON — the offline replay demo needs no Slack workspace."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from .models import InvestigationState, Report, Verdict

logger = logging.getLogger("argus.slack")

_MAX_TEXT = 2900  # Slack section text limit is 3000


def _section(text: str) -> dict[str, Any]:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text[:_MAX_TEXT]}}


def build_blocks(state: InvestigationState, report: Report, elapsed_s: float) -> list[dict[str, Any]]:
    """Design-system layout: header = severity+what+where; 2-col field grid;
    divider-separated sections; secondary metadata in a muted context block;
    actions last. One severity emoji, in the header only."""
    severity = state.alert.labels.get("severity", "critical")
    sev_emoji = {"critical": "🔴", "error": "🔴", "warning": "🟡", "info": "🔵"}.get(severity, "🔴")
    started = state.alert.starts_at.strftime("%H:%M UTC") if state.alert.starts_at else "unknown"
    status = "Needs human review" if report.needs_review else "Root cause verified"
    confirmed_n = sum(1 for h in state.hypotheses if h.verdict == Verdict.confirmed)

    blocks: list[dict[str, Any]] = [
        {"type": "header", "text": {"type": "plain_text",
                                    "text": f"{sev_emoji} RCA: {report.title}"[:150]}},
        {"type": "section", "fields": [
            {"type": "mrkdwn", "text": f"*Severity:*  {severity.capitalize()}"},
            {"type": "mrkdwn", "text": f"*Status:*  {status}"},
            {"type": "mrkdwn", "text": f"*Started:*  {started}"},
            {"type": "mrkdwn", "text": f"*Duration:*  {elapsed_s:.0f}s to RCA"},
            {"type": "mrkdwn", "text": f"*Service:*  {state.service}"},
            {"type": "mrkdwn", "text": f"*Confidence:*  {report.confidence:.0%}"},
        ]},
        {"type": "divider"},
        _section(f"*Root cause{' (draft — flagged for review)' if report.needs_review else ''}:*\n"
                 f"{report.root_cause}"),
    ]
    if report.evidence_bullets:
        bullets = "\n".join(f"• {b}" for b in report.evidence_bullets[:8])
        blocks.append(_section(f"*Evidence:*\n{bullets}"))
    if report.timeline:
        timeline = "\n".join(f"• {t}" for t in report.timeline[:6])
        blocks.append(_section(f"*Timeline:*\n{timeline}"))
    if report.refuted:
        refuted = "\n".join(f"• ~{r}~" for r in report.refuted[:4])
        blocks.append(_section(f"*Ruled out by verification queries:*\n{refuted}"))
    blocks.append({"type": "divider"})
    context_bits = [
        f"🤖 Drafted by ARGUS · `{state.investigation_id}` · LLM: {report.llm_label}",
        f"{confirmed_n}/{len(state.hypotheses)} hypotheses verified · "
        f"{state.usage.llm_calls} LLM calls · "
        f"{state.usage.input_tokens + state.usage.output_tokens} tokens · "
        f"est. ${state.usage.cost_usd:.4f}"
        + (f" · {report.query_stats}" if report.query_stats else ""),
    ]
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": t} for t in context_bits],
    })
    if report.links:
        blocks.append({
            "type": "actions",
            "elements": [{
                "type": "button",
                "text": {"type": "plain_text", "text": "View in SigNoz"},
                "url": report.links[0],
            }],
        })
    return blocks


class SlackPoster:
    def __init__(self, token: str = "", channel: str = "#incidents") -> None:
        self._token = token
        self._channel = channel

    def post(self, blocks: list[dict[str, Any]], fallback_text: str) -> bool:
        """Post to Slack, or dry-run print when no token is configured."""
        if not self._token:
            logger.info("SLACK dry-run (no token): %d blocks built", len(blocks))
            logger.debug("SLACK dry-run blocks:\n%s", json.dumps(blocks, indent=2))
            return False
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers={"Authorization": f"Bearer {self._token}"},
            json={"channel": self._channel, "text": fallback_text, "blocks": blocks},
            timeout=15,
        )
        body = resp.json()
        if not body.get("ok"):
            logger.error("Slack post failed: %s", body.get("error"))
            return False
        return True
