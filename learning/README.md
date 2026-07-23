# ARGUS — Learning Folder

This folder explains ARGUS **twice over**: simply enough for a curious 10-year-old, and precisely enough for a skeptical engineer. It's the teaching companion to the product — every claim here is grounded in ARGUS's own evidence (the runs in `../assets/`, the code in `../src/`), verified against the project's real files rather than paraphrased from memory.

Every file follows the same shape: **In one line → an ELI10 analogy → the real mechanics with real examples → honest limits → why it matters → links to related files.** Illustrations are the hand-drawn explainer set in `../assets/illustrations/`.

> **The one-sentence version:** a SigNoz alert wakes ARGUS; it investigates alone, writes 2–4 falsifiable theories, runs real queries to *disprove* each one, and reports only the survivors with a deep link to the proof — refusing to call a verdict below 75% confidence — while its own LLM calls are traced token-by-token back into the same SigNoz. **The agent that watches your systems is watched by the same system.**

---

## How to read it (pick your path)

- **"Explain it like I'm new"** → [00-the-big-picture.md](00-the-big-picture.md) → [01-how-it-works.md](01-how-it-works.md) → [04-faq/newbie-glossary.md](04-faq/newbie-glossary.md).
- **"I'm evaluating this, give me substance fast"** → [00-the-big-picture.md](00-the-big-picture.md) → [04-faq/hard-questions-answered.md](04-faq/hard-questions-answered.md) → [04-faq/honest-limits-what-we-dont-claim.md](04-faq/honest-limits-what-we-dont-claim.md).
- **"How does it actually work?"** → [01-how-it-works.md](01-how-it-works.md) → [02-signoz-deep-dive.md](02-signoz-deep-dive.md) → [03-the-tech-stack.md](03-the-tech-stack.md).
- **"Tell me the story"** → [05-why-we-built-it-this-way.md](05-why-we-built-it-this-way.md) → [06-bug-hunt.md](06-bug-hunt.md).

---

## The map

- **[00-the-big-picture.md](00-the-big-picture.md)** — why ARGUS exists: the 2am problem, the market gap (the missing OSS AI-SRE for SigNoz), and why we chose it. *For: everyone.*
- **[01-how-it-works.md](01-how-it-works.md)** — the investigation pipeline step by step: webhook → dedup → evidence nodes → hypothesize ⇄ verify → RCA, plus the two replay seams. *For: a smart beginner.*
- **[02-signoz-deep-dive.md](02-signoz-deep-dive.md)** — everything building ARGUS taught us about SigNoz: the v2 rules API, `increase()`-reads-zero, the OpAMP signup gate, `attribute.event.name`, cost-aware querying, and the `gen_ai.*` full circle. *For: engineers.*
- **[03-the-tech-stack.md](03-the-tech-stack.md)** — every technology choice and the honest trade-off: Python/FastAPI, the hand-rolled state machine, the two seams, the bring-your-own-model provider seam (with the measured benchmark), and the testing strategy. *For: engineers.*
- **[04-faq/](04-faq/)** — the Q&A trio:
  - [hard-questions-answered.md](04-faq/hard-questions-answered.md) — the hardest questions a skeptic asks, answered with evidence pointers.
  - [honest-limits-what-we-dont-claim.md](04-faq/honest-limits-what-we-dont-claim.md) — every known limitation, stated plainly.
  - [newbie-glossary.md](04-faq/newbie-glossary.md) — every jargon term, one plain paragraph each.
- **[05-why-we-built-it-this-way.md](05-why-we-built-it-this-way.md)** — how we researched before building: the landscape, the commercial-leader spec, and the three things it changed. *For: everyone.*
- **[06-bug-hunt.md](06-bug-hunt.md)** — the war diary: every real bug (ours, the platform's, and the one ARGUS found in itself), symptom → hunt → root cause → fix → lesson. *For: engineers.*

---

## The five-line cheat sheet

1. **Trigger** — a SigNoz alert POSTs an Alertmanager webhook; ARGUS dedups and starts. Nobody types a question.
2. **Investigate** — a typed state machine gathers golden signals, walks the failing trace (by *self-time*), clusters logs, checks deploys, recalls similar past incidents.
3. **Prove or drop** — the LLM writes falsifiable hypotheses; a no-LLM verify node runs real queries and refutes the ones the telemetry doesn't back; below 75% it self-flags.
4. **Report** — a Slack RCA + postmortem where every claim deep-links into SigNoz, refuted theories are shown, and tokens/dollars are in the footer.
5. **Full circle** — the investigation is itself an `argus.investigation` trace in the same SigNoz; a spend meta-alert can even page ARGUS about ARGUS.
