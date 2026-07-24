"""Unit tests for the `argus slack-setup` wizard.

Everything runs offline: the Slack API is mocked, .env writes go to tmp_path,
and we assert the token value is never printed/logged. No network, no secrets.
"""

from __future__ import annotations

import logging
import stat

import httpx
import pytest

from argus import slack_setup as ss

GOOD_TOKEN = "xoxb-1111111111-2222222222-abcdEFGHijklMNOPqrstUVwx"


# --------------------------------------------------------------------------- #
# Fake httpx transport                                                        #
# --------------------------------------------------------------------------- #
class _FakeResp:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def _patch_post(monkeypatch, body):
    calls = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        calls["url"] = url
        calls["headers"] = headers
        calls["json"] = json
        return _FakeResp(body)

    monkeypatch.setattr(ss.httpx, "post", fake_post)
    return calls


def _patch_get(monkeypatch, body):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _FakeResp(body)

    monkeypatch.setattr(ss.httpx, "get", fake_get)


# --------------------------------------------------------------------------- #
# Token-format validation                                                     #
# --------------------------------------------------------------------------- #
def test_valid_bot_token_shape():
    assert ss.looks_like_bot_token(GOOD_TOKEN)
    assert ss.looks_like_bot_token("  " + GOOD_TOKEN + "  ")  # surrounding whitespace


@pytest.mark.parametrize("bad", [
    "",
    "xoxp-1111-2222-abcd",          # user token
    "xapp-1-A0000-000-abcd",        # app-level token
    "sk-not-a-slack-token",
    "xoxb-",                        # too short
    "bearer xoxb-123456789",        # decorated
])
def test_invalid_bot_token_shapes(bad):
    assert not ss.looks_like_bot_token(bad)


def test_token_format_hint_never_includes_value():
    # The hint describes the mistake, never echoes the token.
    hint = ss.token_format_hint("xoxp-secret-value-here")
    assert "secret-value-here" not in hint
    assert "user" in hint.lower()
    assert "xoxb-" in ss.token_format_hint("garbage")
    assert ss.token_format_hint("") == "no token was provided"


# --------------------------------------------------------------------------- #
# auth.test success / failure                                                 #
# --------------------------------------------------------------------------- #
def test_auth_test_success(monkeypatch):
    calls = _patch_post(monkeypatch, {
        "ok": True, "team": "Acme Inc", "user": "argus", "team_id": "T123",
        "url": "https://acme.slack.com/",
    })
    res = ss.auth_test(GOOD_TOKEN)
    assert res.ok
    assert res.team == "Acme Inc"
    assert res.user == "argus"
    # Token is sent as a Bearer header, not echoed anywhere else.
    assert calls["headers"]["Authorization"] == f"Bearer {GOOD_TOKEN}"


def test_auth_test_invalid_auth_gives_why_try(monkeypatch):
    _patch_post(monkeypatch, {"ok": False, "error": "invalid_auth"})
    res = ss.auth_test(GOOD_TOKEN)
    assert not res.ok
    assert res.error == "invalid_auth"
    assert res.why and res.try_          # human Why/Try populated
    assert "reinstall" in res.try_.lower() or "re-copy" in res.try_.lower()


def test_auth_test_unknown_error_still_graceful(monkeypatch):
    _patch_post(monkeypatch, {"ok": False, "error": "some_new_code"})
    res = ss.auth_test(GOOD_TOKEN)
    assert not res.ok
    assert "some_new_code" in res.why


def test_auth_test_network_error_graceful(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("no route")

    monkeypatch.setattr(ss.httpx, "post", boom)
    res = ss.auth_test(GOOD_TOKEN)
    assert not res.ok
    assert res.error == "network_error"
    assert res.try_  # actionable


# --------------------------------------------------------------------------- #
# conversations.list                                                          #
# --------------------------------------------------------------------------- #
def test_list_channels_sorts_members_first(monkeypatch):
    _patch_get(monkeypatch, {
        "ok": True, "channels": [
            {"id": "C2", "name": "random", "is_member": False},
            {"id": "C1", "name": "incidents", "is_member": True},
        ],
    })
    channels, warning = ss.list_channels(GOOD_TOKEN)
    assert warning == ""
    assert [c.name for c in channels] == ["incidents", "random"]  # member first
    assert channels[0].is_member


def test_list_channels_missing_scope_is_soft(monkeypatch):
    _patch_get(monkeypatch, {"ok": False, "error": "missing_scope"})
    channels, warning = ss.list_channels(GOOD_TOKEN)
    assert channels == []
    assert "optional" in warning  # graceful, not fatal


def test_list_channels_network_error_soft(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("x")

    monkeypatch.setattr(ss.httpx, "get", boom)
    channels, warning = ss.list_channels(GOOD_TOKEN)
    assert channels == [] and warning


# --------------------------------------------------------------------------- #
# chat.postMessage                                                            #
# --------------------------------------------------------------------------- #
def test_send_test_message_success_returns_ts(monkeypatch):
    calls = _patch_post(monkeypatch, {"ok": True, "ts": "1720000000.000100",
                                      "channel": "C1"})
    res = ss.send_test_message(GOOD_TOKEN, "#incidents")
    assert res.ok
    assert res.ts == "1720000000.000100"
    # A real Block Kit sample and fallback text were sent.
    assert calls["json"]["channel"] == "#incidents"
    assert calls["json"]["text"] == ss._TEST_MESSAGE_TEXT
    assert calls["json"]["blocks"][0]["type"] == "header"


def test_send_test_message_not_in_channel_suggests_public_scope(monkeypatch):
    _patch_post(monkeypatch, {"ok": False, "error": "not_in_channel"})
    res = ss.send_test_message(GOOD_TOKEN, "#incidents")
    assert not res.ok
    assert "chat:write.public" in res.try_


def test_send_test_message_missing_scope(monkeypatch):
    _patch_post(monkeypatch, {"ok": False, "error": "missing_scope"})
    res = ss.send_test_message(GOOD_TOKEN, "#incidents")
    assert not res.ok
    assert "chat:write" in res.try_


# --------------------------------------------------------------------------- #
# channel normalization                                                       #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,expected", [
    ("incidents", "#incidents"),
    ("#incidents", "#incidents"),
    ("  alerts ", "#alerts"),
    ("", "#incidents"),
    ("C0123ABCD", "C0123ABCD"),   # channel ID passes through
])
def test_normalize_channel(raw, expected):
    assert ss.normalize_channel(raw) == expected


# --------------------------------------------------------------------------- #
# .env writing: preserves content, chmod 600, no token in logs               #
# --------------------------------------------------------------------------- #
def test_write_env_creates_from_example(tmp_path):
    example = tmp_path / ".env.example"
    example.write_text("SIGNOZ_URL=http://localhost:8080\n"
                       "SLACK_BOT_TOKEN=your-slack-bot-token\n"
                       "SLACK_CHANNEL=#incidents\n")
    env = tmp_path / ".env"
    keys = ss.write_env(
        {"SLACK_BOT_TOKEN": GOOD_TOKEN, "SLACK_CHANNEL": "#alerts"}, env, example
    )
    assert keys == ["SLACK_BOT_TOKEN", "SLACK_CHANNEL"]
    text = env.read_text()
    # Seeded, non-Slack lines preserved.
    assert "SIGNOZ_URL=http://localhost:8080" in text
    # Placeholder replaced in place (not duplicated).
    assert text.count("SLACK_BOT_TOKEN=") == 1
    assert f"SLACK_BOT_TOKEN={GOOD_TOKEN}" in text
    assert "SLACK_CHANNEL=#alerts" in text


def test_write_env_preserves_existing_and_upserts(tmp_path):
    env = tmp_path / ".env"
    env.write_text(
        "# comment line\n"
        "ANTHROPIC_API_KEY=sk-real-key\n"
        "SLACK_CHANNEL=#old\n"
        "\n"
        "OTEL_SERVICE_NAME=argus\n"
    )
    ss.write_env({"SLACK_BOT_TOKEN": GOOD_TOKEN, "SLACK_CHANNEL": "#new"}, env)
    text = env.read_text()
    assert "# comment line" in text
    assert "ANTHROPIC_API_KEY=sk-real-key" in text
    assert "OTEL_SERVICE_NAME=argus" in text
    assert "SLACK_CHANNEL=#new" in text        # updated in place
    assert "SLACK_CHANNEL=#old" not in text
    assert text.count("SLACK_CHANNEL=") == 1
    # Appended key (was absent).
    assert f"SLACK_BOT_TOKEN={GOOD_TOKEN}" in text


def test_write_env_chmod_600(tmp_path):
    env = tmp_path / ".env"
    ss.write_env({"SLACK_BOT_TOKEN": GOOD_TOKEN, "SLACK_CHANNEL": "#x"}, env)
    mode = stat.S_IMODE(env.stat().st_mode)
    assert mode == 0o600


def test_write_env_no_token_in_return_or_logs(tmp_path, caplog):
    env = tmp_path / ".env"
    with caplog.at_level(logging.DEBUG):
        keys = ss.write_env({"SLACK_BOT_TOKEN": GOOD_TOKEN, "SLACK_CHANNEL": "#x"}, env)
    # Return value is names only, never the secret.
    assert GOOD_TOKEN not in keys
    assert all(GOOD_TOKEN not in rec.getMessage() for rec in caplog.records)


def test_write_env_only_touches_requested_keys(tmp_path):
    env = tmp_path / ".env"
    env.write_text("A=1\nB=2\n")
    ss.write_env({"SLACK_BOT_TOKEN": GOOD_TOKEN, "SLACK_CHANNEL": "#x"}, env)
    text = env.read_text()
    assert "A=1" in text and "B=2" in text


# --------------------------------------------------------------------------- #
# Non-interactive run_setup: full mocked path                                 #
# --------------------------------------------------------------------------- #
def test_run_setup_noninteractive_success(tmp_path, monkeypatch, capsys):
    # auth.test + chat.postMessage both succeed; env written to tmp checkout.
    def fake_post(url, headers=None, json=None, timeout=None):
        if url.endswith("auth.test"):
            return _FakeResp({"ok": True, "team": "Acme", "user": "argus"})
        return _FakeResp({"ok": True, "ts": "1.2", "channel": "C1"})

    monkeypatch.setattr(ss.httpx, "post", fake_post)
    monkeypatch.setattr(ss, "project_env_paths",
                        lambda start=None: (tmp_path / ".env", tmp_path / ".env.example"))

    rc = ss.run_setup(token=GOOD_TOKEN, channel="#alerts", assume_yes=True)
    assert rc == 0
    text = (tmp_path / ".env").read_text()
    assert f"SLACK_BOT_TOKEN={GOOD_TOKEN}" in text
    assert "SLACK_CHANNEL=#alerts" in text
    # The token must never appear on stdout/stderr.
    out = capsys.readouterr()
    assert GOOD_TOKEN not in out.out
    assert GOOD_TOKEN not in out.err


def test_run_setup_noninteractive_bad_format_returns_2(tmp_path, monkeypatch):
    monkeypatch.setattr(ss, "project_env_paths",
                        lambda start=None: (tmp_path / ".env", tmp_path / ".env.example"))
    rc = ss.run_setup(token="not-a-token", channel=None, assume_yes=True)
    assert rc == 2
    assert not (tmp_path / ".env").exists()  # nothing written on bad input


def test_run_setup_noninteractive_auth_failure_returns_1(tmp_path, monkeypatch):
    _patch_post(monkeypatch, {"ok": False, "error": "invalid_auth"})
    monkeypatch.setattr(ss, "project_env_paths",
                        lambda start=None: (tmp_path / ".env", tmp_path / ".env.example"))
    rc = ss.run_setup(token=GOOD_TOKEN, channel=None, assume_yes=True)
    assert rc == 1
    assert not (tmp_path / ".env").exists()  # not written when validation fails
