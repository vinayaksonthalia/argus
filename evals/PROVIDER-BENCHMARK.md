# ARGUS provider benchmark

The SAME recorded incidents (real Faultline telemetry) replayed through
different LIVE LLM providers. Comparable signal = hypothesis quality
(did the model propose the ground-truth root cause), latency, tokens,
cost. **Offline caveat:** verification queries a live model invents were
not recorded, so they replay as empty — 'confirmed' counts here reflect
offline verification coverage, NOT live accuracy; run against live
SigNoz for true verification behavior.

_Run count: n=1 per provider×fixture (single-shot; LLM output varies between runs — treat small deltas as noise)._

| provider | fixture | root-cause proposed | service id'd | confirmed (offline) | latency | tokens | cost |
|---|---|---|---|---|---|---|---|
| claude-cli | incident-1 | ✅ | ✅ | 1/4 | 21.5s | 5,668 | $0.0245 |
| claude-cli | incident-2 | ✅ | ✅ | 2/4 | 17.5s | 5,488 | $0.0219 |
| claude-cli | incident-3 | ✅ | ✅ | 3/4 | 19.2s | 5,488 | $0.0219 |
| groq | incident-1 | ❌ | ✅ | 0/6 | 4.7s | 3,277 | $0.0000 |
| groq | incident-2 | ✅ | ✅ | 0/6 | 6.1s | 5,072 | $0.0000 |
| groq | incident-3 | ERROR: node 'hypothesize' failed: JSONDecodeError: Invalid \escape: | — | — | 3.9s | — | — |

## Summary

| provider | root-cause hit rate | median latency | total tokens | total cost |
|---|---|---|---|---|
| claude-cli | 3/3 | 19.2s | 16,644 | $0.0683 |
| groq | 1/2 | 4.7s | 11,523 | $0.0000 |

## n=3 rerun (Jul 17, coordinator-run — raw output: assets/provider-benchmark-n3-runs.txt)

| Provider | Root-cause accuracy (aggregate) | Median latency | Cost/run (avg) |
|---|---|---|---|
| claude-cli (Claude via Max plan) | **8/9 (89%)** | ~19s | ~$0.086 |
| groq (llama-3.3-70b, free) | 3/6 (50%) | ~4s | $0.00 |

Honest notes: groq ran 2 of 3 fixtures per round (one fixture's recorded envelope is claude-shaped; counted only attempted cases). Claude's single miss (run 2) failed the root-cause-keyword check on the bad-deploy fixture — scorecard treats near-miss phrasing as fail. Recommendation unchanged: **claude-cli default for accuracy; groq for cost-free speed where a human reviews every RCA.** Cerebras still blocked on account quota (402).
