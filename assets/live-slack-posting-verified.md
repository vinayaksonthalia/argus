# Live Slack posting — verified

Live Slack posting is **implemented and verified**. With `SLACK_BOT_TOKEN` and
`SLACK_CHANNEL` set (see `.env.example`), `argus investigate --replay` runs the
full replay engine and hands the generated Block Kit RCA to the live Slack sink
(`src/argus/slack.py`), which calls `chat.postMessage`. Without a token the
sink stays in dry-run mode and logs the Block Kit JSON instead of posting.

## Mechanism

Replay engine (deterministic recorded investigation) → RCA report with
`slack_blocks` → live Slack sink (`SlackPoster.post`, `httpx` POST to
`https://slack.com/api/chat.postMessage`). CLI prints `Slack: posted` on a
`200 OK` / `ok: true`, or `Slack: dry-run` when no token is configured.

## Verified runs

| Date       | Investigation   | Result                          |
|------------|-----------------|---------------------------------|
| 2026-07-24 | `inv-1bd6d878ab` | `chat.postMessage` HTTP 200 — output `Slack: posted` |
| 2026-07-25 | `inv-66ed446ae4` | `chat.postMessage` HTTP 200 — output `Slack: posted` |

Both runs POSTed a real Block Kit RCA to a real Slack workspace.

## Status

- Code path: implemented and live-verified twice.
- Screenshot of the posted message in Slack: **captured Jul 25** — see `screenshots/13-slack-personal-test-argus.png` (inv-66ed446ae4 in #incidents, posted by the ARGUS app).
