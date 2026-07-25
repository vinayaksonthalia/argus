# Contributing to ARGUS

Thanks for your interest. ARGUS is small on purpose — an investigation engine, a console, and the seams that keep both testable. Contributions that respect that shape are very welcome.

## Development setup

```bash
git clone https://github.com/vinayaksonthalia/argus && cd argus
uv venv && uv pip install -e ".[dev]"
uv run pytest -q          # 158 tests, fully offline — must stay green
```

The suite runs without a network, an LLM key, or a SigNoz instance; recorded fixtures under `fixtures/` are the contract. If your change needs live verification, `DOCS.md` covers the full loop against a self-hosted SigNoz.

## Ground rules

- **Every gate stays green**: `uv run pytest` before every PR.
- **The honesty invariants are load-bearing.** ARGUS never reports a cause that didn't survive its verification query, never hides refuted or failed hypotheses, and self-flags below the 75% confidence threshold. Changes that soften any of that will not be merged.
- **Read-path only against production**: ARGUS proposes and drafts (disabled rules, dashboards) but never mutates a user's system beyond that. Keep it that way.
- **Zero new runtime dependencies for the console** — it is stdlib-only by design.
- Match the existing code style; add tests with behavior changes; keep docs truthful to what the code does (numbers in docs are re-measured, not estimated).

## Filing issues

Include: what you ran, what you expected, what happened, and — if it's an investigation-quality issue — the `report.json` of the run (postmortems are local files; scrub anything sensitive).

Licensed under MIT; by contributing you agree your work is too.
