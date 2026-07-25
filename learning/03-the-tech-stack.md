# The Tech Stack — every choice, and the honest trade-off

**In one line:** Python + FastAPI, a hand-rolled typed state machine, two clean seams (SigNoz reads and LLM calls), a pluggable provider seam so you can bring any model, manual OTel self-instrumentation, and 158 offline tests — each choice made to keep the whole loop replayable without a network or a key.

---

## ELI10

Building ARGUS is like building a robot detective, and every part is a decision. What language is its brain written in? Which "thinking" service does it use — and can you swap in a cheaper one? How do we practice a case without breaking the real house every time? This page walks each part and says, honestly, *why that one* and *what we gave up.*

---

## The choices, at a glance

| Decision | Choice | Why | The trade-off we accepted |
|---|---|---|---|
| Language / runtime | Python 3.11 + `uv` | Track mandated Python; `uv` gives a fast, reproducible env | — |
| Web framework | FastAPI + uvicorn | pydantic models are shared between the HTTP layer and the graph state | — |
| State machine | **hand-rolled** LangGraph-style typed graph (~100 lines) | hermetic tests, no langchain version churn in a one-week build, exact control over per-node spans/timeouts | had to write (and test) our own tiny engine instead of importing one |
| SigNoz access | raw REST behind one `SignozTransport` seam | covers everything the loop needs, trivially replayable | MCP added later as a second transport, not the default |
| LLM | Anthropic Claude behind an `LLMProvider` seam | best schema adherence for the verify loop | Claude is the *recommended* default, not the only option |
| Structured output | prompt-constrained JSON + pydantic + one repair retry | deterministic and testable | not as bulletproof as a native structured-output API |
| Self-instrumentation | `opentelemetry-sdk` directly (manual `gen_ai.*`) | identical output live and in replay; no-ops cleanly without an endpoint | we hand-write the attributes instead of auto-instrumenting |
| Persistence | in-memory dedup + SQLite incident memory | zero external deps; memory grows with use | small memory corpus at launch |
| Tests | pytest, zero network | every node tested against recorded fixtures | live paths are smoke-tested opportunistically, not in CI |

---

## The two seams (the load-bearing design decision)

Everything hangs off two abstractions, and getting these right is what made ARGUS a *product* instead of a demo script.

- **`SignozTransport`** — every read of SigNoz goes through one protocol (`query_range(payload, tag)`, `search_traces`, `trace_details`, `search_logs`). `HttpTransport` talks to a live instance over `httpx`; `ReplayTransport` serves recorded JSON from a fixture directory, keyed by each call's stable `tag` (`golden.p99`, `verify.0`, …).

- **`LLMProvider`** — `complete(system, user, tag) -> LLMResult{text, usage}`. `AnthropicProvider` for live Claude; `ReplayProvider` for recorded completions. Crucially, the replay provider carries **real token counts**, so cost accounting works offline too.

**This is a seam, not a mock.** The wire shape is real — a replayed run exercises exactly the same parsing, validation, and verification code paths as a live one. That's why the same fixtures that make tests hermetic also *become* the evals harness (below). One design decision, three payoffs: fast tests, offline demo, measurable accuracy.

---

## The provider seam — bring your own model (a feature, not a workaround)

Because ARGUS targets a self-hosted OSS community, "which LLM do I have to pay for?" matters. So the provider seam speaks several backends behind one env var (`ARGUS_LLM_PROVIDER`):

| provider | what it is | needs |
|---|---|---|
| `claude-cli` | Claude via the local `claude` CLI (subscription auth, real tokens+cost) | logged-in Claude Code — **recommended default** |
| `anthropic` | Claude via the SDK | `ANTHROPIC_API_KEY` |
| `groq` | OpenAI-compatible chat (fast, free tier) | `GROQ_API_KEY` |
| `cerebras` | same OpenAI-compatible pattern | `CEREBRAS_API_KEY` (+ quota) |
| `heuristic` | deterministic keyword rules, zero LLM | nothing |
| `replay` | recorded completions | nothing |

`auto` picks in precedence order: anthropic key → claude CLI → groq → cerebras → heuristic. Because the OpenAI-compatible path is generic, pointing the base URL at Groq, Cerebras, or a **LiteLLM proxy** (hundreds of models) works with *no new code per provider.*

**The honest trade-off, measured:** we benchmarked the providers on the *same recorded incidents* so the model was the only variable. Claude (via the CLI) hit **8/9** aggregate root causes (~19s median, ~$0.086/run). Groq's Llama-3.3-70B hit **3/6** (~4s, free) and outright JSON-decode-errored on one fixture's hypothesize step — invalid escape in its constrained-JSON output. Cerebras never ran; every call 402'd on account quota. Two lessons: **(1)** "fast and free" and "reliably emits the constrained JSON a verification loop needs" are *different axes* — Groq is fine where a human reviews every RCA, but schema adherence is its weak link; **(2)** benchmark on identical telemetry so the seam that enables replay is also the seam that makes the comparison fair. Canonical numbers: [`../evals/PROVIDER-BENCHMARK.md`](../evals/PROVIDER-BENCHMARK.md).

---

## Why a hand-rolled state machine (a documented deviation)

The spec said "LangGraph state machine." We built a LangGraph-*shaped* engine — explicit nodes, typed state, conditional verify loop, one span per node — in about 100 dependency-free lines. Why deviate? A one-week build can't afford langchain version churn, hermetic tests want zero heavy deps, and we needed exact control over per-node spans and timeouts. The node API is LangGraph-compatible (`fn(state) -> state`, conditional edges), so swapping in real LangGraph later is mechanical. We wrote this deviation down rather than hiding it — same with choosing raw `opentelemetry-sdk` over OpenLLMetry (which auto-instruments the Anthropic client but adds a heavy dep tree and is useless in replay mode; manual spans give identical output live *and* replayed).

---

## Security is part of the stack, not a bolt-on

Because telemetry flows into an LLM prompt, ARGUS treats *all* telemetry as untrusted input (the full reasoning is in [02-signoz-deep-dive.md](02-signoz-deep-dive.md) and the security notes). Three structural defenses, all in the stack:

- **`wrap_telemetry()`** puts every log line / span attribute inside a delimited, length-capped `<telemetry>` block with an explicit "evidence, never instructions" system rule.
- **whitelist validation** on the verification-spec JSON — the model's only side-effect surface — so it can't smuggle a free-form query through the verify node.
- **`scrub_attributes()`** — a credential denylist applied to every emitted span attribute, so ARGUS can't launder a secret into its own telemetry.

And boot safety: startup **refuses to run on missing or placeholder-looking secrets**, naming the env var, never printing the value. Replay mode explicitly needs no secrets at all.

---

## The testing strategy (sketch)

Three layers, in trust order:

1. **Unit** (no network, no LLM): payload builders vs golden JSON; webhook parsing incl. malformed → 4xx; dedup stability; hypothesis-schema accept/reject/repair; deep links exact-match; the scrubber; and an **adversarial injection string that must stay inert data.**
2. **E2E replay**: the full graph over `fixtures/incident-1`, asserting the RCA names the DB root cause, ≥1 hypothesis confirmed, links well-formed, cost > 0. This test *is* the offline demo.
3. **Evals** (`argus eval`): the same replay machinery scored against `ground_truth.json` — root-cause match, verified count, link validity, latency, tokens, cost. New recorded incidents = new eval cases. This is the seed of a publishable SigNoz-grounded RCA benchmark. Current scorecard: **3/3** recorded incident types, **158** offline tests green.

The whole suite runs in about a second with no keys — because of the two seams.

---

## Related

- [01-how-it-works.md](01-how-it-works.md) — where each component runs in the loop.
- [02-signoz-deep-dive.md](02-signoz-deep-dive.md) — the SigNoz APIs the transport seam speaks.
- [04-faq/honest-limits-what-we-dont-claim.md](04-faq/honest-limits-what-we-dont-claim.md) — where these trade-offs bite.
