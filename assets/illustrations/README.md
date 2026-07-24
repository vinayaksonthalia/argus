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

- `01-the-2am-loop.png` — alert fires → ARGUS wakes (webhook) → reads signals/traces/logs → evidence-linked RCA in Slack; red note: "no human typed anything".
- `02-watched-watcher.png` — ARGUS queries SigNoz while its own gen_ai.* spans (tokens + $ per investigation) flow into the SAME SigNoz; dotted red arrow closes the circle.
- `03-how-it-cant-bluff.png` — three hypotheses → each gets a real falsifiable query → CONFIRMED (90%) / two honest red REFUTED stamps; below 75% confidence it flags itself for human review.
- `04-system-architecture.png` — SigNoz alert webhook → ARGUS server (FastAPI, dedup by fingerprint) → the investigation graph → Slack RCA / postmortem / evidence dashboard & draft rule; LLM provider seam under the graph; coral dotted self-telemetry loop — its own gen_ai.* spans flow back into the SAME SigNoz.
- `05-the-story.png` — a four-panel strip starring **Pager**, the on-call engineer: (1) 2 a.m., paged, exhausted at the laptop as a "checkout p99 > 1s" alert fires; (2) ARGUS is already investigating — a tree of checks builds itself, no question typed; (3) the verdict lands in #incidents with a root cause and evidence that deep-links into SigNoz; (4) Pager goes back to sleep while ARGUS's eye keeps watch over the calm services. Caption: the page fired at 2 a.m. — and the answer was already waiting, you never typed a word.
