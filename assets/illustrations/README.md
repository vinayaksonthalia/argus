# ARGUS explainer illustrations

Hand-sketched-style explainer images (1600x840 landscape, rendered at 2x) for the
README and docs. One big idea per image. Sources in `src/` (self-contained
HTML + the tiny `sketch.js` wobble engine); re-render with
`python3 src/render.py <html> <png>` (playwright, channel=chrome, dsf=2).

The recurring character **Pager** — a small on-call engineer, the reader's proxy —
lives in the shared `character.js` (a seeded-wobble SVG figure with named poses:
`exhausted`, `puzzled`, `aha`, `asleep`, …); `story-builder.js` lays out the
four-panel story strip. Same face/hair/proportions everywhere; only pose and
expression change.

`blog/` holds the three-panel strips written for the blog post; `blog-strip.js`
is the three-panel sibling of `story-builder.js` (same frames, badges, captions
and character treatment, wider panels). Re-render them with:

```bash
python3 src/render.py \
  src/blog-06-the-self-page.html      blog/06-the-self-page.png \
  src/blog-07-it-found-our-bug.html   blog/07-it-found-our-bug.png \
  src/blog-08-what-it-wont-claim.html blog/08-what-it-wont-claim.png
```

- `01-the-2am-loop.png` — alert fires → ARGUS wakes (webhook) → reads signals/traces/logs → evidence-linked RCA in Slack; red note: "no human typed anything".
- `02-watched-watcher.png` — ARGUS queries SigNoz while its own gen_ai.* spans (tokens + $ per investigation) flow into the SAME SigNoz; dotted red arrow closes the circle.
- `03-how-it-cant-bluff.png` — three hypotheses → each gets a real falsifiable query → CONFIRMED (90%) / two honest red REFUTED stamps; below 75% confidence it flags itself for human review.
- `04-system-architecture.png` — SigNoz alert webhook → ARGUS server (FastAPI, dedup by fingerprint) → the investigation graph → Slack RCA / postmortem / evidence dashboard & draft rule; LLM provider seam under the graph; coral dotted self-telemetry loop — its own gen_ai.* spans flow back into the SAME SigNoz.
- `05-the-story.png` — a four-panel strip starring **Pager**, the on-call engineer: (1) 2 a.m., paged, exhausted at the laptop as a "checkout p99 > 1s" alert fires; (2) ARGUS is already investigating — a tree of checks builds itself, no question typed; (3) the verdict lands in #incidents with a root cause and evidence that deep-links into SigNoz; (4) Pager goes back to sleep while ARGUS's eye keeps watch over the calm services. Caption: the page fired at 2 a.m. — and the answer was already waiting, you never typed a word.
- `blog/06-the-self-page.png` — the 23:29 meta-alert, in three beats: the `ARGUS LLM spend rate` alert firing with `service: argus` / `owner: argus`; +30s, investigation `inv-a2a0b2e215` opened against `service = argus`; +55s, the cause it wrote down is its own self-query 400ing. Caption: we wired the loop as a demo, it came back with a real defect — ours.
- `blog/07-it-found-our-bug.png` — the change-correlation bug: `event.name = 'deployment'` shipped → 400 Bad Request, 19 ms, error=True on every investigation, silently → `attribute.event.name`, parsed clean, caught orders 1.1.0-rc1. Caption: the first genuinely new bug it filed was against its own authors.
- `blog/08-what-it-wont-claim.png` — the three non-verdict exits: REFUTED (a hypothesis killed by its own query), DEGRADED (the check won't run / 404s), NEEDS REVIEW (confidence below the 75% bar). Caption: 1 of the 20 runs on the console cleared 75%, the other 19 said so.
