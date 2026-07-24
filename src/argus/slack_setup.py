"""Guided Slack setup for ARGUS — the `argus slack-setup` wizard.

Turns the "read docs, create app, paste token, hope" flow into a ~2-minute
guided experience: it walks the user through creating a Slack app, adding the
right scopes, and installing to the workspace, then LIVE-validates the token
(`auth.test`), lists channels the bot can see (`conversations.list`), sends a
REAL test message (`chat.postMessage`), and writes `SLACK_BOT_TOKEN` +
`SLACK_CHANNEL` into the project `.env` (chmod 600, other lines preserved).

Secrets rule (NFR-5/NFR-6): the token is never printed, logged, or echoed —
prompts mask it, and the .env summary reports *what* was written, not the value.

Pure helpers (token-format validation, the Slack API calls, .env writing) are
kept free of interactive I/O so they unit-test cleanly with a mocked Slack API.
Live calls go through `httpx` (already a dependency — no new heavy deps).
"""

from __future__ import annotations

import logging
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

logger = logging.getLogger("argus.slack_setup")

SLACK_APPS_URL = "https://api.slack.com/apps"
DEFAULT_CHANNEL = "#incidents"
_TIMEOUT = 15

# A bot token is xoxb- followed by digit/hex groups. We validate the *shape*
# only — the real proof is auth.test — but a shape check catches the classic
# mistakes early (pasting a user xoxp- token, an app-level xapp- token, the
# signing secret, or a stray copy of the OAuth code).
_BOT_TOKEN_RE = re.compile(r"^xoxb-[0-9A-Za-z-]{8,}$")

_TEST_MESSAGE_TEXT = "ARGUS connected — this is where investigation reports will arrive"


# --------------------------------------------------------------------------- #
# Token-format validation                                                     #
# --------------------------------------------------------------------------- #
def looks_like_bot_token(token: str) -> bool:
    """True iff `token` has the shape of a Slack *bot* token (`xoxb-…`)."""
    return bool(_BOT_TOKEN_RE.match(token.strip()))


def token_format_hint(token: str) -> str:
    """A human 'Why/Try'-ready reason a token fails the format check.

    Never includes the token value — only a description of the mistake.
    """
    t = token.strip()
    if not t:
        return "no token was provided"
    if t.startswith("xoxp-"):
        return "that is a *user* token (xoxp-); ARGUS needs the *Bot User* token (xoxb-)"
    if t.startswith("xapp-"):
        return "that is an *app-level* token (xapp-); ARGUS needs the *Bot User* token (xoxb-)"
    if not t.startswith("xoxb-"):
        return "a bot token starts with 'xoxb-' — copy it from OAuth & Permissions › Bot User OAuth Token"
    return "the token is too short or has unexpected characters — re-copy the whole xoxb- string"


# --------------------------------------------------------------------------- #
# Live Slack API calls (thin wrappers over httpx)                             #
# --------------------------------------------------------------------------- #
@dataclass
class AuthResult:
    ok: bool
    team: str = ""
    user: str = ""
    team_id: str = ""
    url: str = ""
    error: str = ""  # raw Slack error code / transport error
    why: str = ""
    try_: str = ""


@dataclass
class Channel:
    id: str
    name: str  # without the leading '#'
    is_member: bool = False
    is_private: bool = False


@dataclass
class PostResult:
    ok: bool
    ts: str = ""
    channel_id: str = ""
    error: str = ""
    why: str = ""
    try_: str = ""


# Human 'Why/Try' text for the Slack error codes the wizard can hit. Keeping
# this as data (not scattered conditionals) mirrors the repo's What/Why/Try
# error style and keeps the messages reviewable in one place.
_AUTH_ERRORS = {
    "invalid_auth": (
        "Slack rejected the token as invalid",
        "re-copy the Bot User OAuth Token from OAuth & Permissions (it may have been "
        "truncated, or the app was reinstalled which rotates the token)",
    ),
    "account_inactive": (
        "the token belongs to a deleted or deactivated app/workspace",
        "reinstall the app to the workspace, then copy the fresh xoxb- token",
    ),
    "token_revoked": (
        "this token was revoked",
        "reinstall the app to the workspace to mint a new token",
    ),
    "not_authed": (
        "no token was sent to Slack",
        "paste the xoxb- Bot User OAuth Token when prompted",
    ),
    "token_expired": (
        "the token has expired",
        "reinstall the app to the workspace to get a current token",
    ),
}

_POST_ERRORS = {
    "not_in_channel": (
        "the bot is not a member of that channel",
        "either invite it (type '/invite @YourApp' in the channel) or add the "
        "'chat:write.public' scope in OAuth & Permissions and reinstall — that lets "
        "the bot post to public channels without being invited",
    ),
    "channel_not_found": (
        "no channel by that name/ID is visible to the bot",
        "check the exact channel name, or pick one from the list the wizard showed",
    ),
    "is_archived": (
        "that channel is archived",
        "choose an active channel",
    ),
    "missing_scope": (
        "the bot is missing the 'chat:write' scope",
        "add 'chat:write' under OAuth & Permissions › Scopes and reinstall the app",
    ),
    "restricted_action": (
        "workspace settings block this app from posting there",
        "ask a workspace admin, or choose a channel the app is allowed to post in",
    ),
}


def _explain_auth(code: str) -> tuple[str, str]:
    return _AUTH_ERRORS.get(
        code,
        (f"Slack returned error '{code}'", "see api.slack.com/methods/auth.test for this code"),
    )


def _explain_post(code: str) -> tuple[str, str]:
    return _POST_ERRORS.get(
        code,
        (f"Slack returned error '{code}'",
         "see api.slack.com/methods/chat.postMessage for this code"),
    )


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def auth_test(token: str) -> AuthResult:
    """Call Slack `auth.test`. Returns workspace + bot identity on success, or a
    Why/Try-ready failure. Never raises for a Slack- or network-level error —
    the wizard turns the result into human output."""
    try:
        resp = httpx.post(
            "https://slack.com/api/auth.test",
            headers=_auth_headers(token),
            timeout=_TIMEOUT,
        )
        body = resp.json()
    except httpx.HTTPError as exc:
        return AuthResult(
            ok=False,
            error="network_error",
            why=f"could not reach Slack ({exc.__class__.__name__})",
            try_="check network/proxy connectivity to slack.com and retry",
        )
    if not body.get("ok"):
        code = str(body.get("error", "unknown"))
        why, try_ = _explain_auth(code)
        return AuthResult(ok=False, error=code, why=why, try_=try_)
    return AuthResult(
        ok=True,
        team=str(body.get("team", "")),
        user=str(body.get("user", "")),
        team_id=str(body.get("team_id", "")),
        url=str(body.get("url", "")),
    )


def list_channels(token: str, limit: int = 200) -> tuple[list[Channel], str]:
    """Call `conversations.list` for public+private channels the bot can see.

    Returns (channels, warning). `warning` is non-empty when the call failed or
    was scope-limited — the wizard degrades gracefully (it can still accept a
    typed channel name) rather than aborting.
    """
    try:
        resp = httpx.get(
            "https://slack.com/api/conversations.list",
            headers=_auth_headers(token),
            params={"exclude_archived": "true", "types": "public_channel,private_channel",
                    "limit": limit},
            timeout=_TIMEOUT,
        )
        body = resp.json()
    except httpx.HTTPError as exc:
        return [], f"could not list channels ({exc.__class__.__name__})"
    if not body.get("ok"):
        code = str(body.get("error", "unknown"))
        if code == "missing_scope":
            return [], ("bot is missing 'channels:read' — that scope is optional; "
                        "you can still type the channel name manually")
        return [], f"could not list channels (Slack error '{code}')"
    channels = [
        Channel(
            id=str(c.get("id", "")),
            name=str(c.get("name", "")),
            is_member=bool(c.get("is_member", False)),
            is_private=bool(c.get("is_private", False)),
        )
        for c in body.get("channels", [])
    ]
    channels.sort(key=lambda c: (not c.is_member, c.name))
    return channels, ""


def test_message_blocks() -> list[dict[str, Any]]:
    """A small Block Kit sample proving rich formatting renders — the same
    surface real RCAs use (header + section + context)."""
    return [
        {"type": "header",
         "text": {"type": "plain_text", "text": "✅ ARGUS connected"}},
        {"type": "section",
         "text": {"type": "mrkdwn",
                  "text": "This is where *investigation reports* will arrive — "
                          "an evidence-linked RCA every time a SigNoz alert fires."}},
        {"type": "context",
         "elements": [{"type": "mrkdwn",
                       "text": "🤖 Sent by `argus slack-setup` · you can delete this message"}]},
    ]


def send_test_message(token: str, channel: str) -> PostResult:
    """Post the real 'ARGUS connected' test message. Confirms delivery via the
    returned message `ts`. Never raises — returns a Why/Try-ready failure."""
    try:
        resp = httpx.post(
            "https://slack.com/api/chat.postMessage",
            headers=_auth_headers(token),
            json={"channel": channel, "text": _TEST_MESSAGE_TEXT,
                  "blocks": test_message_blocks()},
            timeout=_TIMEOUT,
        )
        body = resp.json()
    except httpx.HTTPError as exc:
        return PostResult(
            ok=False,
            error="network_error",
            why=f"could not reach Slack ({exc.__class__.__name__})",
            try_="check connectivity to slack.com and retry",
        )
    if not body.get("ok"):
        code = str(body.get("error", "unknown"))
        why, try_ = _explain_post(code)
        return PostResult(ok=False, error=code, why=why, try_=try_)
    return PostResult(ok=True, ts=str(body.get("ts", "")),
                      channel_id=str(body.get("channel", "")))


# --------------------------------------------------------------------------- #
# .env writing (preserve other lines; chmod 600; never echo the token)        #
# --------------------------------------------------------------------------- #
def normalize_channel(channel: str) -> str:
    """Accept '#incidents', 'incidents', or a channel ID (C…). Names get a
    leading '#'; IDs are left as-is (Slack accepts either in chat.postMessage)."""
    c = channel.strip()
    if not c:
        return DEFAULT_CHANNEL
    if re.fullmatch(r"[CG][A-Z0-9]{6,}", c):  # channel/group ID, e.g. C0123ABCD
        return c
    return c if c.startswith("#") else f"#{c}"


def _upsert_env_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    """Return `lines` with each key in `updates` set: existing assignments are
    replaced in place, missing keys appended. Comments/blank lines/other keys
    are preserved verbatim."""
    remaining = dict(updates)
    out: list[str] = []
    for line in lines:
        stripped = line.strip()
        key = ""
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
        if key and key in remaining:
            out.append(f"{key}={remaining.pop(key)}")
        else:
            out.append(line)
    for key, value in remaining.items():
        out.append(f"{key}={value}")
    return out


def write_env(
    updates: dict[str, str],
    env_path: Path,
    example_path: Path | None = None,
) -> list[str]:
    """Write `updates` into `env_path`, preserving every other line, then
    chmod 600. Seeds from `example_path` (typically .env.example) when the
    target .env does not yet exist. Returns the list of keys written (names
    only — callers print these, never the values).
    """
    env_path = Path(env_path)
    if env_path.exists():
        base = env_path.read_text().splitlines()
    elif example_path is not None and Path(example_path).exists():
        base = Path(example_path).read_text().splitlines()
    else:
        base = []

    new_lines = _upsert_env_lines(base, updates)
    content = "\n".join(new_lines).rstrip("\n") + "\n"
    env_path.write_text(content)
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0o600
    except OSError as exc:  # e.g. exotic filesystems — don't fail the whole setup
        logger.warning("could not chmod 600 %s: %s", env_path, exc)
    return list(updates.keys())


def project_env_paths(start: Path | None = None) -> tuple[Path, Path]:
    """Resolve (env_path, example_path) for the project. Prefers the ARGUS
    checkout root (next to pyproject.toml) so the wizard writes the same .env
    the CLI reads; falls back to the current working directory."""
    start = start or Path.cwd()
    # src/argus/slack_setup.py -> parents[2] is the checkout root
    checkout_root = Path(__file__).resolve().parents[2]
    if (checkout_root / "pyproject.toml").exists():
        root = checkout_root
    else:
        root = start
    return root / ".env", root / ".env.example"


# --------------------------------------------------------------------------- #
# Interactive wizard                                                          #
# --------------------------------------------------------------------------- #
def _intro_panel(console: Any, accent: str) -> None:
    from rich.panel import Panel

    console.print()
    console.print(Panel.fit(
        f"[bold {accent}]ARGUS · Slack setup[/]\n\n"
        "This connects ARGUS to your Slack so investigation reports post themselves.\n"
        "Takes about [bold]2 minutes[/]. You'll create a tiny Slack app, grant it\n"
        "permission to post, and paste its token — then this wizard validates it\n"
        "live and sends a real test message.\n\n"
        f"[dim]Open the Slack app dashboard in another tab:[/] [underline]{SLACK_APPS_URL}[/]\n"
        "[dim]Nothing is posted anywhere until the final step, and your token is\n"
        "never printed or logged.[/]",
        border_style=accent,
        title="~2 minutes",
    ))


def _steps_panel(console: Any, accent: str) -> None:
    """The manual clicks the user does in the Slack UI, before we validate."""
    from rich.panel import Panel

    body = (
        f"[bold]1.[/] Go to [underline]{SLACK_APPS_URL}[/] › [bold]Create New App[/] › "
        "[bold]From scratch[/].\n"
        "   Name it (e.g. [italic]ARGUS[/]) and pick your workspace.\n\n"
        "[bold]2.[/] In the left sidebar open [bold]OAuth & Permissions[/].\n\n"
        "[bold]3.[/] Under [bold]Scopes › Bot Token Scopes[/], add:\n"
        "     • [bold]chat:write[/]           — post messages (required)\n"
        "     • [bold]chat:write.public[/]     — post to public channels without being "
        "invited (recommended)\n"
        "     • [dim]channels:read[/]          — optional, lets this wizard list your "
        "channels\n\n"
        "[bold]4.[/] Scroll up and click [bold]Install to Workspace[/] › [bold]Allow[/].\n\n"
        "[bold]5.[/] Copy the [bold]Bot User OAuth Token[/] — it starts with "
        "[bold]xoxb-[/].\n"
        "     [dim](OAuth & Permissions › Bot User OAuth Token, top of the page.)[/]"
    )
    console.print(Panel(body, border_style=accent, title="Do this in the Slack dashboard"))


def _prompt_token(console: Any) -> str:
    """Ask for the xoxb- token with masked input, re-prompting on format errors."""
    from rich.prompt import Prompt

    from . import ui

    while True:
        token = Prompt.ask("[bold]Paste the Bot User OAuth Token[/] (xoxb-…, hidden)",
                           password=True).strip()
        if looks_like_bot_token(token):
            return token
        ui.print_error("that doesn't look like a bot token",
                       why=token_format_hint(token),
                       try_="copy the whole 'xoxb-…' string from OAuth & Permissions")


def _choose_channel(console: Any, accent: str, token: str, assume_yes: bool) -> str:
    """List channels the bot can see and prompt for one (default #incidents)."""
    from rich.prompt import Prompt

    from . import ui

    channels, warning = list_channels(token)
    if warning:
        console.print(f"[dim]Channel list unavailable: {warning}[/]")
    elif channels:
        member = [c for c in channels if c.is_member]
        preview = member or channels
        shown = ", ".join(f"#{c.name}" for c in preview[:12])
        label = "channels the bot is already in" if member else "visible channels"
        console.print(f"[dim]{label}:[/] {shown}"
                      + (" …" if len(preview) > 12 else ""))

    if assume_yes:
        return normalize_channel(DEFAULT_CHANNEL)
    raw = Prompt.ask("[bold]Which channel should reports post to?[/]",
                     default=DEFAULT_CHANNEL)
    channel = normalize_channel(raw)

    # If we have the channel list, warn early when the bot isn't a member and
    # can't post to public channels without chat:write.public.
    if channels and not warning:
        name = channel.lstrip("#")
        match = next((c for c in channels if c.name == name or c.id == channel), None)
        if match and not match.is_member:
            console.print(
                f"[{ui.SEV['warning']}]Heads up:[/] the bot isn't a member of "
                f"#{name}. If it can't post, either invite it "
                f"('/invite @YourApp' in the channel) or add the "
                f"[bold]chat:write.public[/] scope and reinstall."
            )
    return channel


def _run_validation(console: Any, accent: str, token: str, channel: str,
                    assume_yes: bool) -> tuple[bool, str, PostResult | None]:
    """Shared live path: auth.test → send test message. Returns
    (ok, resolved_channel, post_result)."""
    from rich.prompt import Confirm

    from . import ui

    console.print("\n[dim]Validating token with Slack (auth.test)…[/]")
    auth = auth_test(token)
    if not auth.ok:
        ui.print_error("Slack rejected the token", why=auth.why, try_=auth.try_)
        return False, channel, None
    console.print(
        f"[bold {ui.SEV['healthy']}]Token valid[/] — workspace "
        f"[bold]{auth.team}[/], bot [bold]@{auth.user}[/]."
    )

    if not assume_yes:
        if not Confirm.ask(
            f"Send a test message to [bold]{channel}[/] now?", default=True
        ):
            console.print("[dim]Skipped — you can re-run the wizard any time.[/]")
            return False, channel, None

    console.print(f"[dim]Posting test message to {channel} (chat.postMessage)…[/]")
    post = send_test_message(token, channel)
    if not post.ok:
        ui.print_error(f"could not post to {channel}", why=post.why, try_=post.try_)
        return False, channel, post
    console.print(
        f"[bold {ui.SEV['healthy']}]Delivered[/] — message ts "
        f"[dim]{post.ts}[/]. Check {channel} in Slack."
    )
    return True, channel, post


def _closing_panel(console: Any, accent: str, env_path: Path, channel: str,
                   written_keys: list[str]) -> None:
    from rich.panel import Panel

    console.print(Panel.fit(
        f"[bold {accent}]Slack is connected.[/]\n\n"
        f"Wrote [bold]{', '.join(written_keys)}[/] to [bold]{env_path}[/] "
        "(chmod 600).\n"
        "[dim]The token value was not printed.[/]\n\n"
        "[bold]Next:[/]\n"
        "  • See a full RCA post end-to-end:\n"
        "      [bold]uv run argus investigate --replay fixtures/incident-1[/]\n"
        "    (with the token set, the Block Kit RCA posts to "
        f"{channel} instead of dry-run)\n"
        "  • Go live: point a SigNoz alert webhook at "
        "[bold]argus serve[/].\n\n"
        f"[dim]To disable Slack: remove the SLACK_BOT_TOKEN / SLACK_CHANNEL lines from "
        f"{env_path} — ARGUS falls back to dry-run (blocks logged, nothing posted).[/]",
        border_style=accent,
        title="Done",
    ))


def run_setup(
    token: str | None = None,
    channel: str | None = None,
    assume_yes: bool = False,
) -> int:
    """Drive the Slack setup. Interactive when `token` is None; otherwise the
    non-interactive path (scripts) using the same validation + write logic.
    Returns a process exit code (0 ok, 1 validation failure, 2 usage/format).
    """
    from . import ui

    console = ui.console
    accent = ui.ACCENT
    interactive = token is None

    if interactive:
        _intro_panel(console, accent)
        _steps_panel(console, accent)
        token = _prompt_token(console)
    else:
        token = token.strip()
        if not looks_like_bot_token(token):
            ui.print_error("invalid --token format",
                           why=token_format_hint(token),
                           try_="pass the Bot User OAuth Token (xoxb-…)")
            return 2

    resolved_channel = normalize_channel(channel or DEFAULT_CHANNEL)
    if interactive:
        resolved_channel = _choose_channel(console, accent, token, assume_yes)

    ok, resolved_channel, _post = _run_validation(
        console, accent, token, resolved_channel, assume_yes
    )
    if not ok:
        return 1

    env_path, example_path = project_env_paths()
    written = write_env(
        {"SLACK_BOT_TOKEN": token, "SLACK_CHANNEL": resolved_channel},
        env_path, example_path,
    )
    # Report names + the non-secret channel; never the token value.
    console.print(
        f"[dim]Wrote {', '.join(written)} to {env_path} "
        f"(SLACK_CHANNEL={resolved_channel}; token value hidden).[/]"
    )

    if interactive:
        _closing_panel(console, accent, env_path, resolved_channel, written)
    else:
        console.print(f"[bold {ui.SEV['healthy']}]Slack setup complete[/] "
                      f"→ {resolved_channel}")
    return 0
