# Bug Hunt — the war diary

**In one line:** Every real bug we hit building ARGUS — our own, the platform's, and the one ARGUS found in *itself* — each with the symptom, the hunt, the root cause, the fix, and the lesson.

## ELI10

Building anything real means hitting walls. The useful part of a project isn't the shiny demo; it's the list of walls and how we got through each one. Some of these bugs were ours. One was SigNoz's. And the best one, ARGUS found by investigating its own telemetry — the tool caught a bug in the tool. Here's the whole diary.

---

## Bug 1 — the 502 span kept winning over the 2.5-second query (the self-time bug)

- **Symptom:** Our first honest live run (`inv-6bde2d57f9`) confirmed the right *direction* — catalog timing out, gateway returning 502s — but scored itself **60%, below the 75% threshold, and flagged its own report for human review.** It stalled at the symptom instead of naming the cause.
- **The hunt:** We read *why* it stalled. The "culprit span" in its evidence was `GET /api/products http send` on the gateway: **0.07 ms, error=True, status 502.** The trace-dive was picking the *deepest erroring* span. But a gateway forwarding a 502 does so in a near-zero-millisecond span; the actual 25-second `SELECT` was sitting *right below it in the same trace*, unclaimed.
- **Root cause:** Culprit selection ranked by "which span erupted." In a distributed trace, the span that *reports* a failure and the span where the *time went* are usually different spans.
- **The fix:** We rewrote culprit selection to rank by **self-time** (span duration minus its direct children's), which meant plumbing `parent_span_id` through `SpanInfo` and the client. An erroring span now wins only if it *also* holds comparable self-time. Fixture rows without parent IDs keep a guarded legacy fallback. 4 new unit tests.
- **The payoff:** The next fresh live run (`inv-fcdb95f553`) walked straight to catalog's 2507 ms `SELECT`, quoted its `db.statement`, and **verified "pg_sleep(2.5) embedded in the products SELECT" at 90%.**
- **Lesson:** In a distributed trace the loudest span and the guilty span are usually different — **rank causes by where the wall clock was spent, not by who reported the failure.** This one bug fix is what earned the flagship number.

---

## Bug 2 — ARGUS found its own `event.name` bug (the crown jewel)

- **Symptom:** We built the spend meta-alert as a demo trick ("ARGUS pages itself"). It fired for real — `inv-a2a0b2e215`, service: argus — and turned into a defect report.
- **The hunt:** Walking its *own* `gen_ai.*` spans, ARGUS found `signoz.query_range.changes.deployments` erroring on investigation after investigation: **19 ms, error=True, `http.status_code=400`.** Its top hypothesis: ARGUS's own deployment-change self-query is malformed, and the failed call re-enters costly reasoning, inflating spend. The check confirmed it (`found '400 Bad Request' in 2 matching rows`). It *also* generated the escape-hatch hypothesis "this alert is a false positive" and then **killed it with its own query** (`avg cost after/before ratio = 0.77, need > 1.3`, REFUTED).
- **Root cause:** Our change-correlation node filtered deployment events with a **bare `event.name`** where SigNoz's v5 query API wants the context-qualified **`attribute.event.name`.** The bare form makes the parser 400 whenever no deployment event has ever been ingested — which on our stack was *every* investigation, silently, with a retry each time, burning tokens (which is what tripped the spend alert in the first place).
- **The fix:** `event.name` → `attribute.event.name`; regression test added; verified live both with and without deployment events present (the next run cleanly matched a real `orders 1.1.0-rc1` deploy).
- **Lesson, doubled:** (1) an agent that can query its own telemetry is a **second engineer who reads the traces you don't**; (2) we'd shipped a 400-and-retry that **no test caught, because every fixture had well-formed data** — the failure only existed against the live schema. Unedited transcript: `assets/live-meta-alert-argus-pages-itself.txt`.

---

## Bug 3 — the meta-alert rule that read zero forever (`increase()`)

- **Symptom:** The spend meta-alert never fired, even though `argus.cost.usd` was live and visible in SigNoz.
- **The hunt:** Not the wiring, not the metric — both confirmed live. We stared at the rule's aggregation.
- **Root cause:** `increase()`/rate windows assume a **long-running exporter** that keeps observing a counter. ARGUS's emitting process is short-lived — start, one investigation, write cost, exit — so between evaluation points there's no live series to difference, and `increase()` reads 0.
- **The fix:** switched the rule to **`max` aggregation** over the gauge; it fired on the very next spend spike.
- **Lesson:** The aggregation function encodes an assumption about your process lifetime; **a per-invocation agent is not a scraped daemon, and rate-shaped math quietly reads zero on it.**

---

## Bug 4 (platform) — a fresh OpAMP SigNoz silently swallows telemetry

- **Symptom:** Instrumented a service, pointed it at the collector, ran traffic — **nothing errored, and no data appeared.**
- **The hunt:** We were convinced our exporter config was wrong and chased it for real time.
- **Root cause:** On a fresh Foundry-deployed SigNoz, the OpAMP-managed collector comes up with **no OTLP receivers configured until the first UI signup exists.** The receiver the telemetry would land on hasn't been materialized yet.
- **The fix:** sign up in the UI *first*, then instrument.
- **Lesson:** **"No errors and no data" is its own failure signature.** On OpAMP, treat a silent pipeline as *unconfigured*, not broken. (This is now setup-gotcha #1 in our docs.)

---

## Bug 5 — rules 400'd until we read the error body (v2 + notificationSettings)

- **Symptom:** Every alert-rule write 400'd.
- **The hunt:** We were POSTing to `/api/v1/rules` (older material implied it) and retrying blindly.
- **Root cause:** Two things. Current SigNoz serves rules at **`/api/v2/rules`**, and the v2alpha1 body **requires a `notificationSettings` block and ≥1 notification channel — even for a rule created disabled.** The error bodies named the missing field, but only once we stopped retrying and actually read them.
- **The fix:** POST to v2, attach a channel even for our born-`disabled` draft rules. (Live proof: draft rule `019f6d3c-…`, verified `disabled=true`.)
- **Lesson:** On a real platform the request schema *is* the contract, and **"disabled" doesn't exempt you from the required-fields list.**

---

## Bug 6 — verification specs that 404 on nonexistent fields

- **Symptom:** Some hypotheses came back marked `error` — "verification failed to run."
- **Root cause:** The model sometimes writes a spec that aggregates on a field that isn't ingested (e.g. `p99(http.server.duration)` when only `duration_nano` exists). SigNoz returns a hard **404 "field not found,"** not an empty result.
- **The fix (partial):** the verify node marks such hypotheses `error` honestly (it doesn't pretend). A field-catalog hint in the prompt is queued future work.
- **Lesson:** On SigNoz, a nonexistent aggregation field is a **hard 404, not a soft zero** — plan for "wrong answer" *and* "unrunnable question," and let the honest-degradation floor absorb the latter.

---

## Bug 7 (foreign schema) — right culprit, zero-row verification

- **Symptom:** Pointed at SigNoz's own `opentelemetry-demo-lite` (an app we didn't write), ARGUS found the exact `redis: no such host` culprit spans and the correct top hypothesis — then every verification query **matched zero rows.**
- **Root cause:** The falsifiable specs referenced field names and shapes that don't exist in demo-lite's unfamiliar schema.
- **The fix / outcome:** the report **downgraded itself to "degraded — human review required"** rather than claim a verdict it couldn't back. We kept the run as evidence (`assets/demo-lite-generalization-rca.md`).
- **Lesson:** Generalization isn't "it works everywhere" — it's **"it degrades honestly where it can't verify."**

---

## Bug 8 — the overclaim we caught in ourselves (a prose bug, not a code bug)

- **Symptom:** A fresh-eyes internal audit found the thing a hostile reviewer finds in ten seconds: **the flagship "hero" evidence didn't support the flagship claim.** Docs called the 60% live run a "VERIFIED root cause"; the blog told a `pg_sleep`/42.99 hero story with numbers that existed **only in the offline replay.**
- **Root cause:** The *machinery* was honest — runs genuinely self-flag, provenance labels genuinely prevent a replay from masquerading as live — but the *prose* reached past what the machinery had produced.
- **The fix:** Never fake a better run. Instead, **make the words match the receipt** — split the two stories (recorded replay = clean deterministic case, labeled RECORDED; the 60% live run = the honesty system working), then earn a real 90% live run *after* the self-time fix and swap that in as the genuine hero.
- **Lesson:** For an honesty-first product, **one overclaim against your own artifact costs more trust than the feature bought.** The cheapest credibility we ever bought was aligning claim and receipt. (Also fixed in the same audit wave: a silent ancestor-`.env` load that made `argus serve` appear to skip the secret check; test-count drift; hardcoded absolute paths; sub-1.0 ratios rendering as `0.0x`.)

---

## The meta-lesson

Look at the pattern: Bugs 4, 5, and 6 all had the same shape — **the live platform's schema disagreed with what our fixtures assumed.** Bug 2 was the same shape *inside our own code*, caught only because ARGUS could read its own traces. And Bug 8 was that shape applied to our *words.* The recurring lesson of the whole build: **the gap between "something plausible" and "a query proved it" is where all the real work — and all the real bugs — live.** That gap is also, not coincidentally, the entire product.

---

## Related

- [01-how-it-works.md](01-how-it-works.md) — the trace_dive node where the self-time fix landed.
- [02-signoz-deep-dive.md](02-signoz-deep-dive.md) — the platform gotchas (Bugs 3–6) in API detail.
- [04-faq/honest-limits-what-we-dont-claim.md](04-faq/honest-limits-what-we-dont-claim.md) — the limits these bugs revealed.
- [05-why-we-built-it-this-way.md](05-why-we-built-it-this-way.md) — the design rationale and the honesty-as-a-feature story.
