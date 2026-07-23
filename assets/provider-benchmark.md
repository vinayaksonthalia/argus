# ARGUS provider benchmark — moved

The canonical, up-to-date provider benchmark now lives at
[`../evals/PROVIDER-BENCHMARK.md`](../evals/PROVIDER-BENCHMARK.md).

This file used to hold an earlier single-shot (n=1) run whose incident-1 cost
figure ($0.0965, from a 47.6 s / 13,617-token outlier draw) disagreed with the
later, more-representative numbers. To avoid two files quoting different costs
for the same incident, the numbers are kept in exactly one place.

**Headline (from the canonical file, n=3 aggregate):**

| Provider | Root-cause accuracy | Median latency | Cost/run (avg) |
|---|---|---|---|
| claude-cli (Claude via Max plan) | 8/9 (89%) | ~19s | ~$0.086 |
| groq (llama-3.3-70b, free) | 3/6 (50%) | ~4s | $0.00 |
| cerebras | — | — | blocked on account quota (402) |

See `../evals/PROVIDER-BENCHMARK.md` for the per-fixture table, the offline
verification caveat, and the raw run log (`provider-benchmark-n3-runs.txt`).
