# SigNoz Deep Dive — everything building ARGUS taught us about SigNoz itself

**In one line:** ARGUS touches all five SigNoz surfaces — alerts in, traces/logs/metrics read, dashboards/rules written, and its own `gen_ai.*` telemetry written back — and every one of them had a gotcha the docs didn't warn us about.

---

## ELI10

SigNoz is like a giant control room for a computer system: screens for speed (metrics), a map of every request's journey (traces), the diary entries (logs), the alarm bells (alerts), and the wall of dashboards. ARGUS is a robot that has to *use* that whole control room — read the screens, pull the map, ring alarms, and hang new dashboards. Learning to use someone else's control room means learning where the switches secretly stick. This page is our list of the sticky switches.

---

## The surfaces ARGUS uses

| Surface | What ARGUS does with it | API |
|---|---|---|
| **Alerts (trigger in)** | receives the firing alert as a webhook | Alertmanager-compatible POST to `/webhook/signoz` |
| **Traces / logs / metrics (read)** | golden signals, trace dives, log clustering | `POST /api/v5/query_range` |
| **Dashboards (write back)** | auto-creates a per-incident evidence dashboard + Mission Control | `POST /api/v1/dashboards` |
| **Rules (write back)** | draft leading-indicator alert rules; the spend meta-alert | `POST /api/v2/rules` |
| **Self-telemetry (write in)** | its own investigation traces | OTLP with `gen_ai.*` semantic conventions |
| **MCP (optional read path)** | same reads, over the SigNoz MCP server | JSON-RPC `signoz_execute_builder_query` |

Now the sticky switches, in the order they cost us time.

---

## Gotcha 1 — "no errors and no data" is a failure signature (the OpAMP signup gate)

On a fresh Foundry-deployed SigNoz, the OpAMP-managed collector comes up with **no OTLP receivers configured until the first UI signup exists.** So you instrument your service, point it at the collector, run traffic — and *nothing errors.* No connection refused, no dropped-batch warning. The telemetry just goes nowhere, because the receiver it would land on hasn't been materialized yet.

We burned real time convinced our exporter config was wrong. Lesson: **on OpAMP, sign up in the UI *first*, then instrument.** Treat a silent pipeline (no errors *and* no data) as *unconfigured*, not broken. This is now setup-gotcha #1 in our own docs.

---

## Gotcha 2 — rules live at `/api/v2/rules`, and "disabled" doesn't exempt you from required fields

We started wiring alert rules against `/api/v1/rules` because older material implied it. Every write 400'd. Current SigNoz serves alert rules at **`/api/v2/rules`**, and the **v2alpha1** rule shape is stricter than "valid JSON that describes a threshold": it requires a `notificationSettings` block **and at least one notification channel — even for a rule you're creating disabled.**

Our act node POSTs `[DRAFT · ARGUS]` rules that are born `disabled: true`, and it *still* had to attach a channel to get a 2xx. We found both facts the same way: a wall of 400s whose error bodies named the missing field only when we stopped retrying and actually read them. Lesson: **on a real platform the request schema is the contract, and "disabled" doesn't get you out of the required-fields list.** (Live proof: draft rule `019f6d3c-a4d0-7985-b507-9b2f04483e26`, verified `disabled=true` via GET.)

---

## Gotcha 3 — `increase()` reads zero forever for a short-lived process

The spend meta-alert is ARGUS watching its own bill: it emits `argus.cost.usd` as an OTLP metric and a SigNoz rule watches the rate. The rule never fired. Not the wiring, not the metric — both were live and visible. The problem was the **aggregation function.**

`increase()` / rate-style windows assume a **counter that keeps being observed by a long-running exporter.** ARGUS's emitting process is short-lived — it starts, does one investigation, writes its cost, and exits. Between two evaluation points there's often no live series to difference, so `increase()` reads 0. Switching the rule to **`max` aggregation** over the gauge value made it fire on the very next spend spike. Lesson: **the aggregation function encodes an assumption about your process lifetime; a per-invocation agent is not a scraped daemon, and rate-shaped math quietly reads zero on it.**

---

## Gotcha 4 — the v5 query API wants context-qualified attribute names (`attribute.event.name`, not `event.name`)

This is the bug ARGUS found *in itself* (the full war-diary version is in [06-bug-hunt.md](06-bug-hunt.md)). Our change-correlation node filtered deployment events with a **bare `event.name` filter** where SigNoz's v5 query API wants the context-qualified **`attribute.event.name`**. The bare form makes the parser return `400 Bad Request` whenever no deployment event has ever been ingested — which on our stack was *every* investigation, silently, with a retry each time (burning tokens, which is what tripped the spend alert).

Lesson: **v5 `query_range` filter keys are namespaced by context (`attribute.`, `resource.`, `body.`).** A bare key can parse-fail against the live schema in a way no well-formed fixture ever catches.

---

## Gotcha 5 — aggregating on a field that doesn't exist returns 404, and it costs you the hypothesis

Model-proposed verification specs sometimes aggregate on a field that isn't ingested — e.g. `p99(http.server.duration)` when only `duration_nano` exists. `/api/v5/query_range` returns **404 "field not found"** (not an empty result), and the verify node honestly marks that hypothesis `error` ("verification failed to run"). Honest, but it costs the hypothesis. The queued fix is a **field-catalog hint** in the prompt so the model only aggregates on fields that exist; the honest-degradation floor stays regardless. Lesson: **on SigNoz, a nonexistent aggregation field is a hard 404, not a soft zero — plan for both "wrong answer" and "unrunnable question."**

---

## Gotcha 6 — trace operators (`A => B`) generate malformed SQL on this version

We deliberately avoided SigNoz's trace-path operators (`A => B` style span-sequencing) because on the live instance (v0.132.2) they generate malformed SQL. Verified against the running stack, not read from docs. Lesson: **stick to the plain builder-query filter/aggregation surface; the fancier trace-relationship operators are not yet reliable on this version.**

---

## The good part — cost-aware querying is built in

Not every discovery was a wall. SigNoz returns **`meta.rowsScanned` / `bytesScanned` / `durationMs`** on *every* `query_range` response. ARGUS accumulates these per investigation and prints them in the RCA footer: *"23 SigNoz queries · 152,910 rows / 37.0 MB scanned."* An AI agent that can hammer a query API should know what it's costing the database, and SigNoz hands you the numbers to do it. This is a small thing that makes ARGUS feel like a responsible tenant of your stack rather than a runaway query loop.

---

## The full circle — `gen_ai.*` conventions mean zero custom config

The reason ARGUS's own investigations render *natively* in SigNoz's LLM-monitoring views is that we emit standard **`gen_ai.*` OpenTelemetry semantic conventions** — `gen_ai.request.model`, `gen_ai.usage.input_tokens` / `output_tokens` — the exact attributes SigNoz's official OpenAI / LiteLLM / Traceloop integrations emit. So SigNoz's existing LLM views show ARGUS's traces with no custom config, and the spend meta-alert (and the self-found bug) were possible *because* ARGUS's telemetry looks like any other observed LLM app. Lesson: **emit the standard semantic conventions and you inherit the platform's UI for free.**

---

## The MCP path — one tool, chosen deliberately

`ARGUS_TRANSPORT=mcp` routes every SigNoz read through the SigNoz MCP server via JSON-RPC `signoz_execute_builder_query`, behind the same `SignozTransport` seam; a full live investigation ran end-to-end over MCP. We use *that one* tool because it returns the exact v5 envelope including `meta.rowsScanned`. The higher-level MCP tools (`signoz_search_traces` / `signoz_search_logs`) return **LLM-shaped text, not machine-parseable envelopes**, so ARGUS skips them — the verify loop needs structured numbers, not prose. Dashboard and rule writes stay REST-only. Lesson: **MCP is great for reads that return structured envelopes; it's the wrong shape when you need to mechanically evaluate a threshold.**

---

## Related

- [01-how-it-works.md](01-how-it-works.md) — where each of these APIs gets called in the pipeline.
- [06-bug-hunt.md](06-bug-hunt.md) — the `event.name` bug ARGUS diagnosed in its own telemetry, in full.
- [04-faq/newbie-glossary.md](04-faq/newbie-glossary.md) — OTLP, OpAMP, golden signals, query_range, and friends.
- [../DOCS.md](../DOCS.md) — the live-demo commands and the honest "what's still open" list.
