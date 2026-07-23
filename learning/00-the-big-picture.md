# The Big Picture — why ARGUS exists

**In one line:** ARGUS is an AI on-call engineer that wakes up when your pager goes off, investigates the incident alone, tries to *disprove its own theories* with real queries, and hands you an evidence-linked verdict — while being one of the most-observable AI agents you can run, traced token-by-token in the same SigNoz it investigates.

---

## ELI10

Imagine your house has a very good burglar alarm. At 2am it goes *BEEP* — something's wrong. Most "smart" helpers, if you asked them, would say something vaguely reassuring like "maybe check a window." Helpful-ish. But you still have to get out of bed, walk the whole house, and find the actual open window yourself.

ARGUS is different. When the alarm goes off, it doesn't wait for you to ask. It gets up, walks every room, writes down three guesses about what's wrong ("a window? a door? the cat?"), and then — this is the important part — it *goes and checks each guess for real* before telling you anything. It comes back and says: "It's the kitchen window. I checked. The door and the cat were fine, I ruled those out." And it shows you the photo.

That "goes and checks each guess for real" step is the whole personality of ARGUS. It's built so it *can't just make something up.*

---

## The problem, in plain words

When a production system breaks, a human on-call engineer gets paged in the middle of the night. Groggy, stressed, they open three or four dashboards, eyeball latency graphs, dig through traces, grep logs, and try to remember whether anyone deployed anything recently. This is called **triage**, and on a real team it eats **30–40 minutes** of a frightened person's night before they even know *where* the problem is — never mind how to fix it.

The obvious thing to reach for is an LLM. "Hey ChatGPT, my catalog service is slow, what's wrong?" But an LLM answering from vibes is exactly the wrong tool for a 2am outage: it will confidently tell you something plausible, you'll chase it, and it'll be wrong. In an incident, a confident wrong answer is *worse than no answer* — it sends the tired human down a dead end.

So the real problem isn't "can an AI talk about telemetry." It's: **can an AI investigate an incident in a way you'd actually trust at 2am, when being confidently wrong costs you the outage?**

---

## The market gap we aimed at

The AI-observability space is full of tools that *answer questions* about your telemetry — a chatbot you type into. That whole category already exists commercially, too: Cleric, incident.io, Datadog's "Bits AI" — companies with funding, all building AI SREs, all **closed source.**

Here's the gap we saw: SigNoz is a 27,000-star open-source observability platform with a huge self-hosted community, and there was **no open-source autonomous AI SRE** built for it. Every commercial AI-SRE does four things the leaders each brag about — a confidence score with a human-review threshold, every claim traced to a specific datapoint, parallel hypotheses, and a reconstructed incident timeline. Nobody had combined all four in one OSS tool that a self-hosted SigNoz user could actually run. That's the missing piece ARGUS is.

(How we did that research — surveying the landscape, studying what the commercial AI-SRE tools actually ship, and deciding what would genuinely differentiate — is its own story in [05-why-we-built-it-this-way.md](05-why-we-built-it-this-way.md).)

---

## Why *we* chose it

Three reasons, in the order they mattered to us:

1. **The pain is real and felt.** Anyone who has been on-call knows the specific terror of a 2am page and stale dashboards. A demo that opens on that moment lands emotionally, because the engineers evaluating it have lived it.

2. **The differentiator is a substance axis, not a gimmick.** Lots of teams can wire an LLM to an API. Almost none will build the thing that makes an AI answer *trustworthy*: a loop where the agent writes a falsifiable theory, runs a real query that could kill it, and only reports the survivors. We call it the **verified-hypothesis loop**, and it's simultaneously the anti-hallucination story *and* the prompt-injection firewall (more in [01-how-it-works.md](01-how-it-works.md)).

3. **We could make "AI & agent observability" literal.** Most tools read that phrase as "an agent that does observability." We read it both ways: ARGUS observes your systems *and* is fully observed itself. Every LLM call it makes flows back into the same SigNoz as a `gen_ai.*` trace, with tokens and dollars attached. The agent that watches your systems is watched by the same system. That closing image — the watched watcher — is unfakeable if you didn't design for it from day one, and we did.

![ARGUS at 2am: the alert fires, ARGUS wakes on the webhook, reads signals/traces/logs, and posts an evidence-linked RCA — no human typed anything.](../assets/illustrations/01-the-2am-loop.png)

---

## The one-paragraph technical summary

ARGUS is a self-hosted, open-source autonomous incident investigator for SigNoz. A SigNoz alert fires → an Alertmanager-compatible webhook wakes ARGUS → a typed state machine gathers evidence (golden signals before/after, a walk of the failing trace, clustered logs, recent deploys, similar past incidents) → an LLM proposes 2–4 ranked hypotheses, each carrying a **machine-runnable, falsifiable verification spec** → ARGUS executes each check and marks it CONFIRMED or REFUTED → only survivors reach the RCA, every claim deep-links into SigNoz, and below 75% confidence it refuses to call a verdict and self-flags for human review. The whole investigation is itself an `argus.investigation` trace in the same SigNoz, with `gen_ai.*` token and cost accounting per run. The thesis: everyone else builds an AI that *talks about* telemetry; ARGUS is the one you can trust at 2am *because it tries to prove itself wrong first.*

---

## Why it matters

- **The hero beat is visible in one screen.** A fault is injected, an alert fires, and 60 seconds later a Slack card names the exact culprit query with a deep link to the proof — versus 40 minutes of human triage. You *see* the gap.
- **It's honest.** ARGUS's own live runs sometimes score below threshold and flag themselves. We kept those runs as evidence instead of hiding them (see [04-faq/honest-limits-what-we-dont-claim.md](04-faq/honest-limits-what-we-dont-claim.md)). Honesty converts skeptical engineers.
- **It closes the circle.** The demo ends inside the same SigNoz, looking at ARGUS's own trace — tokens, cost, latency per node. Nobody else can show you that.

---

## Related

- [01-how-it-works.md](01-how-it-works.md) — the investigation pipeline, step by step.
- [02-signoz-deep-dive.md](02-signoz-deep-dive.md) — everything we learned about SigNoz's real API.
- [05-why-we-built-it-this-way.md](05-why-we-built-it-this-way.md) — how we decided to build this and not a chatbot.
- [04-faq/hard-questions-answered.md](04-faq/hard-questions-answered.md) — the hard questions, answered with evidence.
