# ARGUS evidence (live verification, July 16–17 2026)

> **Brand assets** (logo, icon, PNG renders + usage): [`brand/`](brand/README.md).

## The live hero run (July 17, after the trace-dive self-time fix)

| file | what it proves |
|---|---|
| `live-e2e-VERIFIED-HERO-inv-fcdb95f553-postmortem.md` / `.report.json` | **the flagship LIVE run**: injected pg_sleep fault → real alert → real webhook → live Claude (claude-cli, haiku-4-5) → **VERIFIED root cause at 90% confidence, above the 75% threshold**, naming the actual injected query — "pg_sleep(2.5) embedded in the products SELECT" — with the culprit 2507ms SELECT span + its `db.statement` in evidence, verification "found 'pg_sleep' in 20 matching rows", 1 confirmed / 1 refuted, memory recall citing three prior incidents, auto-created evidence dashboard + disabled `[DRAFT · ARGUS]` follow-up rule. This is the run the earlier 60% hero couldn't be: it exists because the trace-dive culprit picker now selects the highest **self-time** span (the SELECT doing the work) instead of the gateway's 0ms error-forwarding span. |

All files here were produced against the real self-hosted SigNoz v0.132.2 +
the Faultline demo stack — nothing mocked. UI screenshots pending a signed-in
browser session (agents don't perform logins); every UI-facing claim below is
evidenced via the API instead.

| file | what it proves |
|---|---|
| `faultline-telemetry-verification.txt` | Faultline's 4 services emit real traces+logs into SigNoz (queried via /api/v5/query_range, incl. meta.rowsScanned) |
| `live-e2e-HERO-inv-6bde2d57f9-postmortem.md` / `.report.json` | (July 16 hero, superseded as flagship by `inv-fcdb95f553` above; kept with honest labeling) the full live loop, honestly graded: injected pg_sleep fault → real `/api/v2/rules` alert fired → real webhook → live Claude (claude-cli) investigation → correct root-cause *direction* ("catalog timing out; gateway 502s", confirmed via live log query) at 60% confidence, **auto-flagged for human review** (below the 75% threshold — ARGUS refuses to overclaim), plus deep links, timeline, cost + query footprint and an auto-created evidence dashboard. The clean threshold-clearing 90% pg_sleep RCA is the offline replay of recorded real telemetry: `replay-incident-1-slow-db-cli.txt` |
| `live-e2e-degraded-run-inv-3a51fe90dd-postmortem.md` / `.report.json` | honesty path, live: alert renotified as telemetry recovered → every hypothesis refuted → degraded report flagged for human review + ARGUS self-diagnosis appendix |
| `live-e2e-1-slack-blocks-inv-4199347358.json` | Slack Block Kit RCA payload from the first live investigation (design-system layout; dry-run since no SLACK_BOT_TOKEN) |
| `argus-self-trace-in-signoz.txt` | ARGUS's own gen_ai.* self-observation trace queried back OUT of SigNoz: investigation root span, per-node spans, gen_ai.chat spans with token/cost attrs, per-query spans |
| `dashboards-created-live.txt` | dashboards created via POST /api/v1/dashboards: ARGUS Mission Control + two auto-created per-incident evidence dashboards |
| `eval-scorecard-3-incidents.txt` | 3/3 recorded incidents pass the evals scorecard offline (incident-2/3 recorded from REAL Faultline data with REAL Claude output) |
| `provider-benchmark.md` | same incidents through live claude-cli vs groq vs cerebras — accuracy/latency/tokens/cost comparison (n=1, honest caveats inside) |
| `replay-incident-{1,2,3}-*.txt` | the polished rich-CLI RCA output for each recorded incident (NO_COLOR-safe). incident-1 is the showcase RCA: verified `pg_sleep` root cause at 90%, p99 ratio 42.99, 1 confirmed / 2 refuted — an **offline replay of a recorded real incident** (RECORDED label enforced), not a live run |

## Wave 3 (July 17) — incident memory, meta-alert, draft rules, MCP transport, Foundry cast

| file | what it proves |
|---|---|
| `live-memory-recall-inv-977e5fd4e8-postmortem.md` / `.report.json` | **incident memory, live**: fresh slow-query webhook investigation whose verified RCA cites the July 16 hero incident — root cause ends with "[Incident memory: similar to past incident inv-6bde2d57f9 (similarity 76%)]" plus a "Similar past incidents" section (SQLite + local hashed-TF embeddings, no paid APIs) |
| `live-mcp-transport-inv-5736466ee5-transcript.txt` / `-postmortem.md` | **MCP transport, live**: full investigation with `ARGUS_TRANSPORT=mcp` — every SigNoz read (22 queries incl. golden signals, trace dive, log corr, verification) via JSON-RPC `tools/call signoz_execute_builder_query` on :8000/mcp; banner shows `transport: mcp`; memory recall + a confirmed hypothesis in the right direction at 55% confidence — below the 75% threshold, so the report self-flagged for human review (what the MCP artifact proves is the transport, not an above-threshold RCA) |
| `live-draft-rule-created-by-act-node.json` | **act node draft rule, live**: GET /api/v2/rules/{id} of the follow-up rule the act node created — `disabled: true`, name `[DRAFT · ARGUS] catalog: ...`, labels carry the investigation id; never auto-enabled |
| `live-meta-alert-argus-pages-itself.txt` | **meta-alert, live**: rule on ARGUS's own `argus.cost.usd` OTLP metric (threshold lowered to fire) whose webhook points back at ARGUS → ARGUS receives an alert about ARGUS's spend and investigates itself |
| `foundry-cast-dryrun.txt` | **single-cast packaging**: `foundryctl gauge`+`forge` on `deploy/casting.yaml` generate a valid compose with SigNoz + ARGUS + Faultline (jsonpatch patches); ARGUS Docker image builds, refuses to boot without secrets (NFR-5), healthz OK with them |
| `demo-lite-generalization-rca.md` | **generalization**: investigation on SigNoz/opentelemetry-demo-lite — an app we didn't write (see honest notes inside) |

## Screenshots (captured Jul 17, headless via saved login state — see scratchpad capture_signoz.py pattern)
- screenshots/01-services-list.png — Faultline services live in SigNoz
- screenshots/02-catalog-service-overview.png — catalog latency spike during injected fault
- screenshots/03-mission-control-dashboard.png — ARGUS Mission Control (real gen_ai self-telemetry: investigations, p95 time-to-RCA, token burn, $/run, node latency, queries issued)
- screenshots/04-meta-incident-argus-pages-itself-dashboard.png — auto-created evidence dashboard for meta-investigation inv-a2a0b2e215
- screenshots/05-hero-incident-evidence-dashboard.png — auto-created evidence dashboard for hero incident inv-6bde2d57f9
- screenshots/06-hero-trace-pg-sleep-waterfall.png — gateway 502 → catalog 25s SELECT (pg_sleep) waterfall + span details (the raw telemetry of the injected fault as seen in SigNoz; the live hero RCA pointed at the gateway 502 side of this trace and flagged itself for review — the replay RCA is the one that names the SELECT)
- screenshots/07-traces-explorer.png — traces explorer over Faultline traffic
- screenshots/08-alert-rules-incl-draft.png — catalog alert FIRING + ARGUS spend meta-alert FIRING (meta: argus-pages-itself) + five [DRAFT · ARGUS] act-node rules

Investigations Console (`argus console`, captured Jul 24, headless retina via scratchpad capture_console.py — a LOCAL read-only web UI rendering the real postmortems/, no login required, unlike the SigNoz shots above):
- screenshots/09-console-list.png — the console populated from all 20 recorded investigations: left rail newest-first with color-coded confidence badges (VERIFIED/NEEDS REVIEW/DEGRADED) + per-run cost, header stats strip (20 investigations · 5% verified · $0.94 total spend), GLASSPANE browser-error incident selected showing verdict + confidence ring, root cause, impact, timeline. (The strip is honest: this corpus is mostly self-flagged runs — 1 VERIFIED, 13 needs-review, 6 degraded — because ARGUS refuses to overclaim.)
- screenshots/10-console-detail.png — detail view of the VERIFIED 90% pg_sleep hero (inv-fcdb95f553) scrolled to the hypotheses: one CONFIRMED ✓ (green) naming the injected query, two verification-errored (amber), one REFUTED ✗ (muted red) — the confirmed/refuted flex — above the Evidence list with clickable "view in SigNoz ↗" deep-links.

Slack (captured Jul 25, Vinayak's own workspace):
- screenshots/13-slack-personal-test-argus.png — the live-posted Block Kit RCA in #incidents (workspace "Personal test"), posted by the ARGUS app via chat.postMessage for inv-66ed446ae4: severity/status header, verified root cause at 90%, evidence bullets with "view in SigNoz" links, timeline, ruled-out hypotheses struck through, and the honest cost footer ("LLM: replay … RECORDED — replayed LLM output, not a live call · 1/3 hypotheses verified · est. $0.0187"). This is the screenshot the live-slack-posting-verified.md evidence note previously listed as pending.

- illustrations/ — three hand-sketched explainer illustrations (2am loop, watched watcher, how it can't bluff); see illustrations/README.md
