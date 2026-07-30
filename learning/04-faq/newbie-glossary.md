# Newbie Glossary

**In one line:** Every nerdy word in the ARGUS docs, explained the way you'd explain it to a smart 10-year-old, with one line tying it back to ARGUS.

## ELI10

Grown-ups invented a lot of fancy words for simple ideas. This page un-fancies them. Read any term you bumped into and you'll get a plain picture plus how *we* actually use it. Terms are alphabetical; each ends with **→ in ARGUS:** so you always see the real connection.

---

### agent (AI agent)
A program that doesn't just answer one question — it takes an action, looks at the result, decides the next step, and repeats, toward a goal.
**→ in ARGUS:** ARGUS is an agent — it wakes on an alert and drives a whole multi-step investigation on its own, no human in the loop.

### Alertmanager / webhook
A **webhook** is a "phone call" one program makes to another when something happens — it POSTs a little message to a URL. **Alertmanager** is the common format Prometheus/SigNoz use for those alert messages.
**→ in ARGUS:** a SigNoz alert POSTs an Alertmanager-compatible webhook to ARGUS's `/webhook/signoz`, which is what starts everything.

### confidence threshold (75%)
A cutoff for how sure the system has to be before it's allowed to state a conclusion. Below it, it says "I'm not sure" instead of guessing.
**→ in ARGUS:** below the review bar (**75%** by default) ARGUS refuses to call a verdict and ships an evidence-only report flagged for human review. The bar drops to 65% when incident memory recalls the same failure class and that past incident was itself verified — earned confidence, always stated in the report.

### deduplication (dedup)
Noticing that two messages are really *the same* event and not doing the work twice.
**→ in ARGUS:** a re-delivered alert is fingerprinted (alertname + service + 5-minute window) so it returns the existing investigation instead of starting a new one.

### deep link
A URL that opens *the exact spot* in another app — not the front page, but the specific trace/log/query.
**→ in ARGUS:** every claim in the RCA deep-links to the precise SigNoz query that backs it, so you can check the proof in one click.

### falsifiable hypothesis
A guess written so that a specific test *could prove it wrong.* "It's the database" isn't falsifiable; "there will be more than 1 row containing 'pg_sleep'" is.
**→ in ARGUS:** every LLM hypothesis must include a falsifiable verification spec — a real query with a threshold — so it can be mechanically killed.

### `gen_ai.*` (semantic conventions)
Agreed-on standard names for describing an LLM call in telemetry — model name, input tokens, output tokens. Standard names mean any tool understands them.
**→ in ARGUS:** ARGUS emits `gen_ai.request.model`, `gen_ai.usage.input_tokens`, etc., so SigNoz's existing LLM views render ARGUS's own traces with zero custom config.

### golden signals
The four vital signs of a service: latency, traffic, errors, saturation. Check these first in any incident.
**→ in ARGUS:** the `golden_signals` node queries p99 latency, error rate, and throughput before *and* after the alert to see what changed.

### hallucination
When an LLM makes something up that sounds confident but isn't backed by the facts it was given.
**→ in ARGUS:** the whole verify/refute loop exists to catch this — an unbacked claim is refuted, not reported.

### hypothesis ⇄ verify loop
The core cycle: the model guesses (hypothesize), ARGUS tests the guesses with real queries (verify), and if all guesses die it loops back to guess again with the disproof in hand.
**→ in ARGUS:** capped at 2 iterations so it always terminates; this loop is both the anti-hallucination story and the injection firewall.

### `increase()` / aggregation function
A math rule for summarizing a metric over time. `increase()` measures how much a counter grew; `max` takes the biggest value seen.
**→ in ARGUS:** `increase()` read zero on ARGUS's short-lived process; switching the spend rule to `max` made it fire (see [../02-signoz-deep-dive.md](../02-signoz-deep-dive.md)).

### LLM provider seam
A swappable slot for "which AI brain to use," so you can change the model without changing the code.
**→ in ARGUS:** `ARGUS_LLM_PROVIDER` picks Claude, Groq, Cerebras, a deterministic rule engine, or a recorded replay — bring your own key.

### MCP (Model Context Protocol)
A standard way for AI tools to call other tools/servers, like a universal adapter for "let the model use this capability."
**→ in ARGUS:** `ARGUS_TRANSPORT=mcp` routes SigNoz reads through the SigNoz MCP server; a full investigation ran end-to-end over it.

### OpAMP
A protocol for a central server to *remotely configure* your telemetry collectors.
**→ in ARGUS:** a fresh OpAMP-managed SigNoz has no OTLP receiver until the first UI signup — which is why "no errors and no data" is a failure signature.

### OTLP
**OpenTelemetry Protocol** — the standard wire format for shipping traces/metrics/logs to an observability backend.
**→ in ARGUS:** ARGUS exports its own investigation traces over OTLP (usually to `:4318`) so they land in the same SigNoz.

### postmortem
The written-up story of an incident: what happened, why, what we found.
**→ in ARGUS:** every investigation writes a markdown postmortem to `postmortems/`, alongside the Slack card.

### RCA (root cause analysis)
Figuring out the *actual underlying reason* something broke, not just the symptom.
**→ in ARGUS:** the final output is an RCA — verdict, confidence, evidence links, timeline, and cost.

### refuted / confirmed
The two verdicts a hypothesis can get after ARGUS tests it. Refuted = the query disproved it; confirmed = the query backed it.
**→ in ARGUS:** the RCA proudly shows the *refuted* theories and the queries that killed them — the flex that separates it from "AI said X" bots.

### replay / seam
A **seam** is a clean swap-point in the code. **Replay** means feeding recorded data through that seam instead of live data.
**→ in ARGUS:** the `SignozTransport` and `LLMProvider` seams let a whole recorded incident replay offline — same code paths, no network, no keys.

### self-time
A span's *own* duration minus the time spent inside its children — i.e. where the wall clock actually went in *this* step.
**→ in ARGUS:** ranking culprit spans by self-time (instead of "which span erupted") is the fix that took a live run from 60% to 90%.

### span / trace
A **trace** is the full journey of one request through a system; a **span** is one step of that journey (one service call, one query).
**→ in ARGUS:** the `trace_dive` node walks the failing trace's spans to find the guilty one; and each ARGUS node is itself a span in an `argus.investigation` trace.

### token / cost accounting
LLMs bill by **tokens** (chunks of text). Counting them tells you what a run cost.
**→ in ARGUS:** every RCA footer prints tokens and dollars; the spend meta-alert watches `argus.cost.usd` and can page ARGUS about its own bill.

### verification spec
The little machine-runnable test attached to each hypothesis: what kind of check, what parameters, what result would confirm it.
**→ in ARGUS:** this JSON is the model's *only* side-effect surface, and it's whitelist-validated before any query is built — the security boundary.

---

## Related

- [hard-questions-answered.md](hard-questions-answered.md) — the FAQ that uses all these terms.
- [honest-limits-what-we-dont-claim.md](honest-limits-what-we-dont-claim.md) — the honest boundaries.
- [../01-how-it-works.md](../01-how-it-works.md) — the terms in action across the pipeline.
- [../02-signoz-deep-dive.md](../02-signoz-deep-dive.md) — deeper on the SigNoz-specific terms.
