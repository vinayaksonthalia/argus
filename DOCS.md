# ARGUS — plain-English docs

_Last verified live: July 17, 2026 (against SigNoz v0.132.2 self-hosted via Foundry)._

## What works today (all live-verified, evidence in `assets/`)

- **The full autonomous loop, live** (`assets/README.md` indexes the
  artifacts). The flagship LIVE run `inv-fcdb95f553` (July 17, after the
  trace-dive self-time fix): injected fault → real alert → real webhook →
  live Claude → **verified root cause at 90% confidence, above the 75%
  threshold**, naming the actual injected query ("pg_sleep(2.5) embedded in
  the products SELECT", verification: "found 'pg_sleep' in 20 matching
  rows"), with an auto-created evidence dashboard and a disabled draft
  follow-up rule (`assets/live-e2e-VERIFIED-HERO-inv-fcdb95f553-postmortem.md`).
  Earlier live runs are kept with honest labeling: the July 16 run
  `inv-6bde2d57f9` confirmed the right root-cause *direction* at 60% and
  **auto-flagged itself for human review** (ARGUS refuses to overclaim below
  threshold), and the honesty run (recovering telemetry → all hypotheses
  refuted → degraded + self-diagnosis). The polished deterministic showcase —
  the same pg_sleep RCA replayed from recorded real telemetry — is
  `fixtures/incident-1` (labeled RECORDED,
  `assets/replay-incident-1-slow-db-cli.txt`). Mechanics: Faultline demo
  services emit real
  OTLP telemetry into SigNoz → a real threshold alert rule
  (`POST /api/v2/rules`, p99 > 1s on `catalog`) fires → SigNoz's webhook
  notification channel POSTs to ARGUS → ARGUS investigates against the live
  SigNoz query API → a real Claude model (via the local `claude` CLI) forms
  hypotheses → each hypothesis is mechanically verified with real queries →
  an RCA with deep links, timeline, confidence score, and cost accounting is
  produced, plus a per-incident evidence dashboard is auto-created via
  `POST /api/v1/dashboards`.
- **Self-observation**: every investigation is an `argus.investigation`
  trace in the same SigNoz — one span per graph node, one
  `gen_ai.chat <model>` span per LLM call with `gen_ai.usage.input_tokens`/
  `output_tokens` and `argus.cost.usd`, one `signoz.query_range.<tag>` span
  per read with `argus.signoz.rows_scanned` — see
  `assets/argus-self-trace-in-signoz.txt`.
- **Query-cost self-awareness**: SigNoz returns
  `meta.rowsScanned/bytesScanned/durationMs` on every query_range response;
  ARGUS accumulates it per investigation and prints it in the RCA footer
  ("23 SigNoz queries · 152,910 rows / 37.0 MB scanned").
- **Incident memory** (`argus-memory.sqlite3`, SQLite + local hashed-TF
  embeddings — zero paid APIs): every completed investigation is stored; at
  hypothesize time the top-3 similar past incidents are recalled as evidence
  and high-similarity matches are cited in the RCA. Live-verified (the recall
  mechanism; the run itself scored 60% and self-flagged for human review): a
  fresh slow-query investigation's root cause ends with "[Incident memory:
  similar to past incident inv-6bde2d57f9 (similarity 76%)]" — the July 16
  hero incident (`assets/live-memory-recall-inv-977e5fd4e8-postmortem.md`).
  Inspect/backfill with `argus memory list|recall|add-report`.
- **Spend meta-alert (ARGUS pages itself)**: `argus.cost.usd` is now also an
  OTLP *metric*; `scripts/setup_meta_alert.py` creates a real
  `/api/v2/rules` alert on its hourly increase whose webhook points back at
  ARGUS — the agent is governed by the same alerting it consumes
  (`assets/live-meta-alert-argus-pages-itself.txt`).
- **Draft follow-up alert rules (act node)**: on a CONFIRMED root cause the
  act node maps the winning verification spec onto a leading-indicator
  threshold rule and POSTs it to `/api/v2/rules` as `[DRAFT · ARGUS] …` with
  `disabled: true` — never auto-enabled; a human reviews and flips it on.
  Live-verified (`assets/live-draft-rule-created-by-act-node.json`).
- **MCP transport option**: `ARGUS_TRANSPORT=mcp` serves every SigNoz read
  through the SigNoz MCP server (`tools/call signoz_execute_builder_query`
  over JSON-RPC at :8000/mcp) behind the same `SignozTransport` seam; REST
  stays the default. A full live investigation ran end-to-end over MCP —
  22 reads incl. verification queries
  (`assets/live-mcp-transport-inv-5736466ee5-transcript.txt`).
- **Foundry single-cast install**: `deploy/casting.yaml` deploys SigNoz +
  ARGUS (containerized, `deploy/Dockerfile`) + Faultline in one
  `foundryctl cast`, using casting-file `patches` (RFC 6902) to add the extra
  services to the generated pours. Validated by `foundryctl gauge` + `forge`
  dry-run + `docker compose config` (`assets/foundry-cast-dryrun.txt`).
- **Three recorded incidents** (`fixtures/incident-{1,2,3}`: slow-db,
  error-storm, bad-deploy — 2 and 3 recorded from REAL Faultline telemetry
  with REAL Claude output) replay offline and pass the evals scorecard 3/3.
- **Offline test suite**: 143 tests, no network, no LLM (`uv run pytest`).

## The Investigations Console (`argus console`)

A read-only local web UI that makes the investigation corpus browsable —
closing ARGUS's one weak spot (previously its only surfaces were the CLI, the
Slack payload, and markdown files). It renders **only from local files** ARGUS
already writes; it never calls an LLM or SigNoz, needs no API key, and binds
`127.0.0.1` only.

```bash
uv run argus console                       # http://127.0.0.1:7332
uv run argus console --port 7500 --postmortem-dir postmortems
```

- **Data source.** Each `postmortems/<id>.report.json` is the structured RCA
  contract; the sibling `<id>.md` supplies the metadata header (service, alert,
  date) and the token/$ cost line the JSON omits; the incident-memory SQLite is
  a fallback for service/alert/date, and `postmortems/metadata.json` is a
  last-resort fallback carrying that same recorded metadata for the committed
  corpus (both `.md` files and the memory DB are per-run output and gitignored,
  so without it a clean clone would show `unknown · undated`). The list re-reads
  on each page load, so a new RCA landing in `postmortems/` shows up on refresh.
- **Layout.** Left rail = every investigation newest-first (undated reports
  group last rather than sorting by their random-hex id) with a confidence
  badge (green `VERIFIED` ≥75% · amber `NEEDS REVIEW` <75% · red `DEGRADED` =
  all hypotheses refuted) and cost. A rail toolbar filters by service / alert /
  id and by status chip with live counts. Main pane = verdict header + confidence
  ring, root cause, impact, timeline, hypotheses stamped `CONFIRMED ✓` /
  `REFUTED ✗` / errored, evidence deep-links into SigNoz (`localhost:8080`),
  similar-past-incident citations, and a token/$/queries/rows cost footer. A
  header stats strip shows totals (count, verified %, total spend) computed from
  the data. Empty/loading/error states follow the design system.
- **Keyboard.** `/` focuses the filter, `↑`/`↓` or `j`/`k` walk the rail, `Enter`
  in the filter opens the first match, `Escape` clears it. Every investigation is
  addressable by URL fragment (`#inv-…`), so an RCA can be linked to directly.
- **Static export.** `uv run python scripts/export_console.py` writes the whole
  console to `docs/` as plain files — same `render.py`/`data.py`, one detail
  fragment per investigation — so the corpus browses with no Python running:
  `python3 -m http.server -d docs 8000`. Regenerate it after any console change;
  the exporter aborts if it can no longer find the console's fetch call, so the
  export cannot silently drift from the product it depicts.
- **Security (this is the point).** Postmortem text is telemetry-derived and
  therefore untrusted — GLASSPANE's audit found an XSS in exactly this
  render-telemetry-into-a-page pattern. The console renders every dynamic value
  server-side through `html.escape`, drops non-`http(s)` link schemes
  (`javascript:`/`data:`), whitelists the `inv-…` id path segment, and ships a
  restrictive CSP. `tests/test_console.py` feeds hostile
  `<script>`/`<img onerror>`/`javascript:` payloads through the real renderer
  and asserts they come out as inert escaped text, never live markup.
- **Zero dependency.** Built on the standard library's `http.server` (same
  key-holding-proxy viewer pattern as GLASSPANE's session-timeline, vanilla JS,
  no npm) — it adds nothing to `pyproject.toml`. `assets/screenshots/09-console-list.png`
  and `10-console-detail.png` are live captures against the real 20-report corpus.

## Configuration & `.env` search order (explicit, no silent ancestor walking)

ARGUS loads config from the environment; `.env` files are read in this
documented order (real environment variables always win, and the first file
that sets a variable wins over later files):

1. `./.env` in the directory you run `argus` from
2. the ARGUS project's own `.env` (next to `pyproject.toml`, checkout runs)
3. deliberate fallback: the project's **parent** directory `.env` — in this
   monorepo that is the shared secrets file at the repo root

There is no further walking up the tree — an unrelated ancestor `.env` can
never be silently picked up.

## Connecting Slack (`argus slack-setup`)

The guided, ~2-minute path from "no Slack" to "RCAs land in a channel". It is
the **primary** way to set `SLACK_BOT_TOKEN` + `SLACK_CHANNEL`; the manual
`.env` route (below) remains a supported fallback.

```bash
uv run argus slack-setup                                   # interactive wizard
uv run argus slack-setup --token xoxb-… --channel '#x' --yes   # scripted / CI
```

What it does, in order:

1. **Intro + steps** — explains the ~2-minute flow and links
   [api.slack.com/apps](https://api.slack.com/apps), then walks the Slack-UI
   clicks: create app (from scratch) → OAuth & Permissions → add `chat:write`
   (required) and `chat:write.public` (recommended — post to public channels
   without being invited; `channels:read` is optional and only lets the wizard
   list channels) → Install to Workspace → copy the **Bot User OAuth Token**.
2. **Token entry** — masked input, re-prompts on a bad shape. Format check is
   `xoxb-…`; it distinguishes a user token (`xoxp-`) or app-level token
   (`xapp-`) and says so, without ever echoing the value.
3. **Live validation** — `auth.test` (prints the workspace + bot name on
   success; a What/Why/Try message on failure), then `conversations.list` to
   show channels the bot can see (graceful if the scope is missing — you can
   still type a name; default `#incidents`).
4. **Real test message** — `chat.postMessage` posts a small Block Kit sample
   ("ARGUS connected …") and confirms delivery via the returned `ts`. A
   `not_in_channel` failure tells you to invite the bot or add
   `chat:write.public`.
5. **Writes `.env`** — creates it from `.env.example` if absent, upserts the
   two keys **preserving every other line**, `chmod 600`, and prints *what* was
   written (never the token).
6. **Closing** — next steps (`argus investigate --replay …` to see a full RCA
   post; disable = remove the two lines).

Secrets rule: the token is never printed, logged, or written to stdout/stderr —
prompts mask it and the summary reports key names + the (non-secret) channel
only. Exit codes: `0` ok, `1` live-validation failure (nothing written), `2`
bad `--token` format. No new dependencies — the wizard uses `httpx` (already
present) for the three Slack calls.

## The LLM provider seam (honesty rules)

`ARGUS_LLM_PROVIDER=auto|anthropic|claude-cli|heuristic`

| provider | what it is | needs |
|---|---|---|
| `anthropic` | Claude via SDK | `ANTHROPIC_API_KEY` |
| `claude-cli` | Claude via the local `claude` CLI in headless print mode (`-p --output-format json`); real tokens + cost from the CLI envelope | logged-in Claude Code (subscription) |
| `groq` | OpenAI-compatible chat completions at api.groq.com (free-tier fallback; tokens recorded, cost $0.00). **Live-verified** (llama-3.3-70b-versatile). | `GROQ_API_KEY` |
| `cerebras` | same, at api.cerebras.ai (default model `gpt-oss-120b`). Auth + /models verified live; chat completions returned **402 Payment Required on this account** — works once the account has quota. | `CEREBRAS_API_KEY` |
| `heuristic` | deterministic keyword rules, zero LLM | nothing |
| replay | recorded completions from a fixture | nothing |

`auto` precedence: anthropic key → claude CLI → groq key → cerebras key → heuristic.

### Bring your own key (product feature, not a workaround)

| you have… | set | notes |
|---|---|---|
| a Claude subscription (Max/Pro) | nothing — `claude` CLI logged in | **recommended default** |
| an Anthropic API key | `ANTHROPIC_API_KEY` | same models via SDK |
| a free Groq account | `GROQ_API_KEY` | fast + free; quality is model-dependent |
| a Cerebras account with quota | `CEREBRAS_API_KEY` | same OpenAI-compatible pattern |
| nothing / CI | — | replay fixtures + `heuristic` provider |

Which model is good enough? Run the benchmark on the recorded incidents:

```bash
uv run argus eval fixtures/incident-* --providers claude-cli,groq --report evals/PROVIDER-BENCHMARK.md
```

Claude stays the recommended default: the verification loop's quality (how
falsifiable and well-scoped the proposed checks are) is provider-dependent,
and the benchmark table in `evals/PROVIDER-BENCHMARK.md` shows the gap.

Every RCA is labeled with its provider: live runs say e.g.
`claude-sonnet-4-5-... (live)`, replays say `replay:<model> (RECORDED — replayed
LLM output, not a live call)`, heuristic runs say `(DETERMINISTIC — rule-based,
no LLM)`. A recorded run can never masquerade as a live one.

## Run the live demo in 5 commands

```bash
# 0. prerequisites: SigNoz up on :8080 (Foundry), root .env has SIGNOZ_API_KEY,
#    `claude` CLI logged in. From argus/:

# 1. bring up Faultline (4 services + Postgres, OTLP -> host SigNoz)
docker compose -f services/faultline/docker-compose.yaml up -d --build

# 2. seed SigNoz: webhook channel -> ARGUS + the catalog-latency alert rule (v2 API)
uv run python scripts/setup_live.py && uv run argus init-dashboards

# 3. start ARGUS (self-traces flow back into the same SigNoz)
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318 uv run argus serve

# 4. generate traffic + inject the fault (new terminal)
python3 services/faultline/loadgen.py --rps 2 --duration 1800 &
services/faultline/faultctl inject slow-query

# 5. watch: within ~2 minutes the rule fires, SigNoz POSTs the webhook, and
curl localhost:7331/investigations   # ... the RCA lands in postmortems/
```

Cleanup: `services/faultline/faultctl clear all`.

Offline demo (no SigNoz, no LLM, no secrets):
`uv run argus investigate --replay fixtures/incident-1` and
`uv run argus eval fixtures/incident-1 fixtures/incident-2 fixtures/incident-3`.

Record a new incident fixture from live data:
`uv run python scripts/record_incident.py fixtures/incident-4 --alert scripts/alerts/error-storm.json`.

## What's still open (honest)

- **Anthropic SDK path untested live** — no API key on this machine; the seam
  is exercised by the `claude-cli` provider instead (same prompt, same JSON
  contract, real Claude models).
- **Slack posting is live-verified** — `chat.postMessage` posts the Block Kit
  RCA to a real workspace when `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` are set (per
  `.env.example`); verified HTTP 200 (runs inv-1bd6d878ab, inv-66ed446ae4, see
  `assets/live-slack-posting-verified.md`). Without a token it stays dry-run
  and the design-system-compliant Block Kit JSON is logged/saved instead. The
  `argus slack-setup` wizard's live paths (token-format check, `auth.test`
  graceful-failure UX, `.env` writing) are unit-tested with a mocked Slack API
  and exercised against the real `auth.test` endpoint with an invalid token; a
  full happy-path wizard run (real `auth.test`/`chat.postMessage` success) needs
  a valid workspace token.
- **UI screenshots** need a signed-in SigNoz browser session (agents can't
  perform logins); all UI-facing claims are evidenced via API queries in
  `assets/` until then.
- **Memory corpus is small** (a handful of incidents) — similarity quality
  grows with use; the local hashed-TF embedding trades recall quality for
  zero external dependencies (documented, deliberate).
- **MCP transport uses one tool** (`signoz_execute_builder_query`) because it
  returns the exact v5 envelope incl. `meta.rowsScanned`; the higher-level
  MCP tools (signoz_search_traces/logs) return LLM-shaped text, not
  machine-parseable envelopes, so ARGUS skips them. Dashboard/rule writes
  stay REST-only.
- **Full `foundryctl cast` not executed on this machine** — it would collide
  with the already-running SigNoz (same ports); generation was dry-run
  validated (`forge` + `docker compose config`), run steps documented
  in `deploy/casting.yaml`.
- Trace operators (`A => B`) deliberately avoided — they generate malformed
  SQL on SigNoz v0.132.2 (verified against the live instance; notes live in
  the repo-root research folder, one level above `argus/`:
  `../research/signals-playbook.md` §1.7 — not shipped inside this project).
- **A bug ARGUS found in itself (and we then fixed):** the spend
  meta-investigation (inv-a2a0b2e215) walked ARGUS's *own* spans in SigNoz
  and root-caused a recurring erroring `signoz.query_range.changes.deployments`
  span — the change-correlation node's bare `event.name = 'deployment'`
  filter makes SigNoz's parser 400 whenever no deployment event was ever
  ingested. Fixed by switching to the context-qualified
  `attribute.event.name` form (parses cleanly, returns zero rows); regression
  test added, verified live both with and without deployment events present.
  Evidence: `assets/live-meta-alert-argus-pages-itself.txt`.
- **Model-proposed verification specs can 404**: aggregating on a field that
  does not exist (e.g. `p99(http.server.duration)` when only `duration_nano`
  is ingested) returns 404 "field not found" from `/api/v5/query_range`; the
  verify node marks such hypotheses `error` ("verification failed to run") —
  honest, but it costs the hypothesis. A field-catalog hint in the prompt is
  future work.
