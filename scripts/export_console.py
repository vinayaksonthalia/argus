#!/usr/bin/env python3
"""Export the Investigations Console to a static, serverless bundle in ``docs/``.

The console is normally served by ``argus console`` (stdlib ``http.server``),
which fetches each RCA from ``/api/detail/<id>``. This script renders exactly
the same HTML with the same ``render.py``/``data.py`` code and writes every
detail fragment to a file, so the whole console browses from a plain static
directory — no Python, no SigNoz, no keys.

It exists so ``docs/`` is a *reproducible artifact* rather than a hand-edited
snapshot that silently drifts from the real console. Regenerate after any
console change:

    uv run python scripts/export_console.py

Verify:

    python3 -m http.server -d docs 8000   # then open http://localhost:8000
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from argus.console import data, render  # noqa: E402

# The single *behavioural* difference between the served console and the static
# one: where a detail fragment comes from. Everything else — markup, CSS, the
# filter/keyboard logic — comes from the same render.py, so the export can't
# drift from the product. (The published bundle also renders the landing hero;
# that too is a render.py flag, not a post-hoc edit of the output.)
_LIVE_FETCH = "fetch('api/detail/' + encodeURIComponent(id))"
_STATIC_FETCH = "fetch('detail/' + encodeURIComponent(id) + '.html')"


def export(postmortem_dir: Path, out_dir: Path) -> int:
    invs = data.load_investigations(postmortem_dir)
    if not invs:
        raise SystemExit(f"no investigations found in {postmortem_dir}")

    # hero=True is the one deliberate difference in *content*: the published
    # bundle is a landing page for someone who has never heard of ARGUS, so it
    # gets the introduction band. `argus console` is a working tool for someone
    # who already has it installed, so it keeps the plain topbar.
    page = render.render_page(invs, data.compute_stats(invs), hero=True)
    if _LIVE_FETCH not in page:
        raise SystemExit(
            "export is stale: the console's fetch call changed shape.\n"
            f"expected to find: {_LIVE_FETCH}\n"
            "update _LIVE_FETCH in scripts/export_console.py to match render.py"
        )
    page = page.replace(_LIVE_FETCH, _STATIC_FETCH)

    detail_dir = out_dir / "detail"
    if detail_dir.exists():
        shutil.rmtree(detail_dir)
    detail_dir.mkdir(parents=True, exist_ok=True)
    for inv in invs:
        (detail_dir / f"{inv.id}.html").write_text(
            render.render_detail(inv), encoding="utf-8"
        )

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(page, encoding="utf-8")
    return len(invs)


if __name__ == "__main__":
    n = export(ROOT / "postmortems", ROOT / "docs")
    print(f"exported {n} investigations -> docs/index.html + docs/detail/*.html")
