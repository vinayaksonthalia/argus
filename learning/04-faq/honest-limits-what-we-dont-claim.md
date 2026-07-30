# Honest Limits — what we do NOT claim

**In one line:** The boundaries of ARGUS, stated plainly — because an honesty-first product's credibility lives entirely in the alignment between its claims and its artifacts.

## ELI10

A good scientist doesn't say "my model is perfect." They say "it predicts the lava, but not the exact day, and here's why." That honesty is what makes people believe the parts that *do* work. This is our list of "here's what ARGUS can't do" — and for a project whose whole pitch is "an AI you can trust because it proves itself wrong," saying the limits out loud isn't a weakness. It's the pitch.

---

## Limit 1 — it's read-only advice, not autonomous remediation

**We do NOT claim** ARGUS fixes incidents, restarts services, or runs any command against production.

It **reads** telemetry and **tells you what it found.** A human reads the RCA and acts. The one thing it writes back — a `[DRAFT · ARGUS]` follow-up alert rule — is always born `disabled: true`; a human enables it. It also creates evidence dashboards, which are additive and destructive of nothing. There is no `kubectl`, no prod credentials, no execution path. This is deliberate: "self-healing" teams that wire an LLM to mutate prod have a scarier demo and a much weaker safety story. An agent you trust to *talk* beats a bot you've wired to *touch* prod.

---

## Limit 2 — an LLM can be confidently wrong; verification is the mitigation, not a guarantee

**We do NOT claim** ARGUS is always right, or that a clean verify pass is proof of truth.

Retrieved context is *influence*, not law — a model can confabulate or, rarely, contradict clear evidence. The verify/refute loop dramatically curbs this by refusing to report any claim a real query doesn't back, and by self-flagging below 75% confidence. But verification checks *"does the telemetry support this specific claim,"* not *"is this the deepest possible truth."* We treat ARGUS as a **hypothesis generator with a kill-switch, not an oracle.** That's why every claim carries a deep link to its proof — so a human can check the receipt in one click.

---

## Limit 3 — model-proposed checks can be unrunnable (the 404 field problem)

**We do NOT claim** every verification query succeeds.

Sometimes the model writes a spec that aggregates on a field that isn't ingested (e.g. `p99(http.server.duration)` when only `duration_nano` exists). SigNoz returns a hard **404 "field not found,"** and the verify node honestly marks that hypothesis `error` — "verification failed to run." That's the honest outcome, but it *costs* the hypothesis. A field-catalog hint in the prompt is queued future work; the honest-degradation floor stays regardless.

---

## Limit 4 — generalization means "degrades honestly," not "works everywhere"

**We do NOT claim** ARGUS verifies cleanly on any codebase.

On a foreign app (SigNoz's `opentelemetry-demo-lite`) ARGUS found the right `redis: no such host` culprit spans but its verification queries matched zero rows against the unfamiliar schema, so the report **downgraded itself to "degraded — human review required."** We kept that run as evidence on purpose. The evidence *pipeline* generalizes; the *verification* is only as good as its schema awareness, and where it can't verify, it says so instead of bluffing.

---

## Limit 5 — the memory corpus is small at launch

**We do NOT claim** incident memory has deep recall.

Similar-past-incident recall runs on local SQLite with hashed-TF embeddings (deliberately zero paid APIs). At launch the corpus is a handful of incidents, so similarity quality is modest and grows with use. The local embedding trades recall quality for zero external dependencies — a documented, deliberate choice, not an accident.

---

## Limit 6 — single-service blast radius only

**We do NOT claim** multi-service correlation.

ARGUS analyzes the failing service and the traces that pass through it. Correlating a root cause *across* multiple services (true blast-radius analysis) is roadmap, not shipped.

---

## Limit 7 — some surfaces are demonstrated by API evidence, not screenshots

**We do NOT claim** things we couldn't capture.

Slack posting is **live-verified** — with `SLACK_BOT_TOKEN` + `SLACK_CHANNEL` set, `chat.postMessage` posts the Block Kit RCA to a real workspace (HTTP 200; runs inv-1bd6d878ab, inv-66ed446ae4). Without a token it stays dry-run: the design-compliant Block Kit JSON is logged instead of posted. The `argus slack-setup` wizard is the guided path to those two variables — its token-format check, `auth.test` graceful-failure UX, and `.env` writing are unit-tested with a mocked Slack API and run against the real `auth.test` endpoint with an invalid token; a full happy-path wizard run (real `auth.test`/`chat.postMessage` **success**) still needs a valid workspace token, so we don't claim that leg is captured here. The Anthropic *SDK* path is untested live on this machine (no API key here) — the same prompt and JSON contract are exercised via the `claude-cli` provider instead, with real Claude models. And UI screenshots need a signed-in browser session headless capture can't perform, so UI-facing claims are evidenced via API queries in `assets/` until a human captures them. We label each of these open items rather than implying they're done.

---

## Limit 8 — provider quality varies, and we measured it

**We do NOT claim** every model works equally well.

Claude (via the CLI) hit 8/9 root causes on the benchmark; Groq's Llama-3.3-70B hit 3/6 (faster, free) and JSON-decode-errored on one fixture's constrained output; Cerebras 402'd on quota. "Fast and free" and "reliably emits the constrained JSON a verify loop needs" are different axes. Claude is the *recommended* default for accuracy; Groq is fine where a human reviews every RCA. We publish the gap rather than implying model-independence.

---

## The one-paragraph version (for a reader in a hurry)

ARGUS is **read-only advice**, not autonomous remediation — its only write-backs are disabled draft rules and additive dashboards. An LLM can be confidently wrong, so verification is a **kill-switch, not a truth oracle**: it refuses unbacked claims and self-flags below 75%. Model-proposed checks can still fail on missing fields (the hypothesis is then reported as untested, not refuted, and the next iteration is told to write a runnable spec), and on a foreign schema ARGUS **degrades honestly to "human review"** rather than pretending. Memory is small at launch, blast-radius is single-service, Slack posting is live-verified (dry-run default without a token), and model quality varies (Claude 8/9, Groq 3/6, measured). And the honesty machinery is load-bearing: our own audit caught prose that over-reached past the artifacts, and the cheapest credibility we ever bought was making the words match the receipt.

---

## Related

- [hard-questions-answered.md](hard-questions-answered.md) — the full FAQ.
- [newbie-glossary.md](newbie-glossary.md) — definitions for confidence threshold, self-time, OpAMP, and more.
- [../06-bug-hunt.md](../06-bug-hunt.md) — how we found these limits (including the overclaim we caught in ourselves).
- [../../DOCS.md](../../DOCS.md) — the canonical "what's still open (honest)" list.
