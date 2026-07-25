"""Tests for the read-only Investigations Console.

Two concerns:
  1. The report parser reconstructs an Investigation from the real on-disk
     contract (report.json + sibling .md).
  2. SECURITY: postmortem text is telemetry-derived and therefore untrusted.
     GLASSPANE's audit found an XSS in exactly this render-telemetry pattern.
     These tests prove injected <script> / <img onerror> / javascript: URLs
     render INERT (escaped text / dropped href), never as live markup.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from argus.console import data as cdata
from argus.console import render
from argus.console.server import ConsoleData, make_handler  # noqa: F401 (import smoke)

XSS_IMG = '<img src=x onerror="window.__pwned=1">'
XSS_SCRIPT = "<script>window.__pwned=2</script>"


def _write_report(dirpath: Path, inv_id: str, payload: dict, md: str | None = None) -> Path:
    p = dirpath / f"{inv_id}.report.json"
    p.write_text(json.dumps(payload))
    if md is not None:
        (dirpath / f"{inv_id}.md").write_text(md)
    return p


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def test_load_investigation_from_real_postmortems():
    # Integration check against a small curated corpus of real postmortems. Most
    # ``*.md`` postmortems and the runtime memory DB are gitignored (per-run
    # output), but a few real ones are committed via .gitignore negations so a
    # clean checkout has live .md-backed data (see postmortems/inv-0d3daf4f0f.md).
    # Skip gracefully only if that curated corpus was removed.
    pm_dir = Path("postmortems")
    fixture_md = pm_dir / "inv-0d3daf4f0f.md"
    if not (pm_dir.is_dir() and fixture_md.is_file()):
        pytest.skip("real .md-backed postmortem corpus not present in this checkout")
    invs = cdata.load_investigations(Path("postmortems"), Path("argus-memory.sqlite3"))
    assert len(invs) >= 20, "expected the real recorded postmortems to load"
    ids = {i.id for i in invs}
    assert "inv-0d3daf4f0f" in ids
    inv = next(i for i in invs if i.id == "inv-0d3daf4f0f")
    assert inv.service == "meridian-web"
    assert inv.alert == "GLASSPANE: browser error spike"
    assert inv.cost.tokens_in == 4777 and inv.cost.tokens_out == 1151
    assert inv.cost.usd == pytest.approx(0.0295)
    assert "SigNoz queries" in inv.cost.query_stats
    # at least one confirmed + some refuted/errored hypotheses reconstructed
    verdicts = {h.verdict for h in inv.hypotheses}
    assert "CONFIRMED" in verdicts
    assert inv.evidence and any(e.url.startswith("http") for e in inv.evidence)
    assert inv.similar, "similar-past-incident citations should be split out"


def test_reports_sorted_newest_first():
    invs = cdata.load_investigations(Path("postmortems"), Path("argus-memory.sqlite3"))
    dates = [i.date_sort for i in invs if i.date_sort]
    assert dates == sorted(dates, reverse=True)


def test_undated_reports_sort_after_dated_ones(tmp_path):
    """An undated report has no timestamp, so it must not be interleaved.

    Sorting it by its id would be sorting by random hex — which used to push
    a 0%-confidence draft above a real, dated investigation in the rail.
    """
    base = {"root_cause": "", "impact": "", "timeline": [], "evidence_bullets": [],
            "refuted": [], "degraded": False, "needs_review": False}
    hdr = "- **Service:** `s`\n- **Alert:** `a`\n- **Generated:** {} UTC\n"
    _write_report(tmp_path, "inv-0000aa", {**base, "title": "old", "confidence": 0.9},
                  hdr.format("2026-07-16 10:00"))
    _write_report(tmp_path, "inv-ffff99", {**base, "title": "new", "confidence": 0.9},
                  hdr.format("2026-07-18 10:00"))
    # no sibling .md -> no date at all, despite an id that sorts high
    _write_report(tmp_path, "inv-ffffff", {**base, "title": "undated", "confidence": 0.9})

    ids = [i.id for i in cdata.load_investigations(tmp_path)]
    assert ids == ["inv-ffff99", "inv-0000aa", "inv-ffffff"]


def _inv(inv_id, conf, degraded=False, date=""):
    return cdata.Investigation(
        id=inv_id, title="t", service="s", alert="a", date_display=date,
        date_sort=date, confidence=conf, degraded=degraded, needs_review=False,
        root_cause="", impact="",
    )


def test_default_selection_prefers_the_best_verified_run():
    """The console opens on the strongest verified RCA, not the latest draft."""
    # newest-first, as load_investigations returns them
    invs = [
        _inv("inv-newest", 0.55, date="2026-07-20"),   # NEEDS REVIEW
        _inv("inv-hero", 0.90, date="2026-07-18"),     # VERIFIED
        _inv("inv-ok", 0.80, date="2026-07-17"),       # VERIFIED, weaker
        _inv("inv-bad", 0.99, degraded=True, date="2026-07-16"),  # DEGRADED
    ]
    assert cdata.default_selection(invs).id == "inv-hero"


def test_default_selection_falls_back_to_newest_without_a_verified_run():
    invs = [
        _inv("inv-newest", 0.55, date="2026-07-20"),
        _inv("inv-older", 0.70, date="2026-07-18"),
    ]
    assert cdata.default_selection(invs).id == "inv-newest"
    assert cdata.default_selection([]) is None


def test_default_selection_ties_go_to_the_newer_run():
    invs = [_inv("inv-newer", 0.90, date="2026-07-20"),
            _inv("inv-older", 0.90, date="2026-07-18")]
    assert cdata.default_selection(invs).id == "inv-newer"


def test_exactly_one_row_is_marked_as_the_landing_view():
    invs = [
        _inv("inv-newest", 0.55, date="2026-07-20"),
        _inv("inv-hero", 0.90, date="2026-07-18"),
    ]
    html = render.render_list(invs)
    assert html.count("data-default") == 1
    # the mark lands on the hero's row, not the newest one
    hero_row = html[html.index('data-id="inv-hero"'):]
    assert hero_row[: hero_row.index("</button>")].count("data-default") == 1
    # ...and the rail order is untouched: newest still renders first
    assert html.index('data-id="inv-newest"') < html.index('data-id="inv-hero"')


def test_rail_rows_carry_filter_metadata(tmp_path):
    """The client-side filter matches service / alert / id — and only those."""
    _write_report(
        tmp_path, "inv-abc123",
        {"title": "T", "confidence": 0.9, "root_cause": "", "impact": "",
         "timeline": [], "evidence_bullets": [], "refuted": [],
         "degraded": False, "needs_review": False},
        "- **Service:** `catalog`\n- **Alert:** `p99 breach`\n"
        "- **Generated:** 2026-07-20 10:00 UTC\n",
    )
    invs = cdata.load_investigations(tmp_path)
    row = render.render_row(invs[0])
    assert 'data-status="VERIFIED"' in row
    assert 'data-search="catalog p99 breach inv-abc123"' in row
    # listbox options must expose selection state to assistive tech
    assert 'aria-selected="false"' in row

    page = render.render_page(invs, cdata.compute_stats(invs))
    assert 'id="filter"' in page
    assert 'data-filter="VERIFIED"' in page
    # statuses with no investigations don't get a dead chip
    assert 'data-filter="DEGRADED"' not in page


def test_hidden_attribute_actually_hides_rows(tmp_path):
    """Regression: `.row{display:block}` outranks the UA sheet's [hidden] rule.

    The rail filter hides rows by setting the ``hidden`` attribute. Without an
    explicit override the rows kept rendering — the JS property read as hidden
    while the user saw an unfiltered list, which is the worst kind of bug to
    assert your way past. So assert the override exists, ahead of any display:
    declaration that could shadow it.
    """
    page = render.render_page([], cdata.Stats(total=0, verified=0, total_usd=0.0))
    assert "[hidden]{display:none !important}" in page
    assert page.index("[hidden]{display:none") < page.index(".row{")


def test_filter_toolbar_hidden_when_there_is_nothing_to_filter(tmp_path):
    page = render.render_page([], cdata.Stats(total=0, verified=0, total_usd=0.0))
    assert 'id="filter"' not in page
    assert "No investigations yet." in page


def test_status_badge_thresholds():
    def mk(conf, degraded=False):
        return cdata.Investigation(
            id="inv-1", title="t", service="s", alert="a", date_display="",
            date_sort="", confidence=conf, degraded=degraded, needs_review=False,
            root_cause="", impact="",
        )
    assert mk(0.90).status == "VERIFIED"
    assert mk(0.75).status == "VERIFIED"
    assert mk(0.60).status == "NEEDS REVIEW"
    assert mk(0.0).status == "NEEDS REVIEW"
    assert mk(0.90, degraded=True).status == "DEGRADED"


def test_hypothesis_classification():
    hyps = cdata._parse_hypotheses(
        root_cause="A slow query in catalog. (verified: found pg_sleep in 20 rows)",
        refuted=[
            "Traffic surge caused it. — verification: before/after p99 unchanged",
            "Upstream API broke. — verification failed to run: 400 Bad Request",
        ],
        degraded=False,
    )
    assert hyps[0].verdict == "CONFIRMED"
    assert "pg_sleep" in hyps[0].detail
    assert hyps[1].verdict == "REFUTED"
    assert hyps[2].verdict == "ERROR"


def test_degraded_has_no_confirmed_hypothesis():
    hyps = cdata._parse_hypotheses(
        root_cause="No hypothesis survived. (verified: n/a)",
        refuted=["X. — verification: refuted"],
        degraded=True,
    )
    assert all(h.verdict != "CONFIRMED" for h in hyps)


def test_stats_computation():
    invs = [
        cdata.Investigation(id="a", title="", service="", alert="", date_display="",
                            date_sort="", confidence=0.9, degraded=False,
                            needs_review=False, root_cause="", impact="",
                            cost=cdata.Cost(usd=0.02)),
        cdata.Investigation(id="b", title="", service="", alert="", date_display="",
                            date_sort="", confidence=0.5, degraded=False,
                            needs_review=True, root_cause="", impact="",
                            cost=cdata.Cost(usd=0.03)),
    ]
    s = cdata.compute_stats(invs)
    assert s.total == 2 and s.verified == 1 and s.verified_pct == 50
    assert s.total_usd == pytest.approx(0.05)


# --------------------------------------------------------------------------
# SECURITY: XSS escaping (the flagged pattern)
# --------------------------------------------------------------------------

def test_esc_neutralizes_html():
    out = render.esc(XSS_IMG)
    assert "<img" not in out and "&lt;img" in out
    assert "onerror" in out  # still visible as text for the analyst
    assert render.esc(XSS_SCRIPT) == "&lt;script&gt;window.__pwned=2&lt;/script&gt;"


def test_safe_url_drops_dangerous_schemes():
    assert render.safe_url("javascript:alert(1)") == ""
    assert render.safe_url("data:text/html,<script>1</script>") == ""
    assert render.safe_url("http://localhost:8080/x") == "http://localhost:8080/x"
    # a hostile url that tries to break out of the attribute is escaped, not raw
    out = render.safe_url('http://x/"><img src=y onerror=alert(1)>')
    assert "<img" not in out and '"' not in out


def test_detail_render_escapes_hostile_telemetry(tmp_path):
    payload = {
        "title": f"Alert {XSS_IMG}",
        "root_cause": f"root {XSS_SCRIPT} cause (verified: found {XSS_IMG})",
        "confidence": 0.9,
        "impact": f"p99 {XSS_IMG}",
        "timeline": [f"12:00 {XSS_SCRIPT}"],
        "evidence_bullets": [
            f"log signature: {XSS_IMG} (<javascript:alert(1)|view in SigNoz>)",
            "p99 breach (<http://localhost:8080/x?a=1|view in SigNoz>)",
        ],
        "refuted": [f"bad idea {XSS_IMG}. — verification: refuted"],
        "degraded": False,
        "needs_review": False,
        "query_stats": f"3 queries {XSS_IMG}",
    }
    md = (
        "# Postmortem\n"
        f"- **Service:** `svc {XSS_IMG}`\n"
        f"- **Alert:** `alert {XSS_SCRIPT}`\n"
        "- **Generated:** 2026-07-20 10:00 UTC\n"
        "## Cost\n- LLM: evil-model\n- LLM calls: 1, tokens: 10 in / 5 out, est. $0.0001\n"
    )
    report = _write_report(tmp_path, "inv-deadbeef", payload, md)
    inv = cdata.load_investigation(report)

    html = render.render_detail(inv)
    # No live markup anywhere.
    assert "<img" not in html
    assert "<script>window.__pwned" not in html
    assert "onerror=" not in html or "onerror=&" in html  # only inside escaped text
    # The dangerous evidence link scheme was dropped: it never becomes an href
    # (it survives only as inert, escaped text, which is safe).
    assert "href=\"javascript:" not in html
    assert "href='javascript:" not in html
    assert "&lt;javascript:alert(1)" in html  # rendered as text, not a link
    # The safe SigNoz deep-link survives.
    assert 'href="http://localhost:8080/x?a=1"' in html
    # Content is still present, escaped, so analysts can read it.
    assert "&lt;script&gt;" in html


def test_full_page_render_escapes_list(tmp_path):
    payload = {
        "title": f"T {XSS_SCRIPT}", "root_cause": "", "confidence": 0.5,
        "impact": "", "timeline": [], "evidence_bullets": [], "refuted": [],
        "degraded": False, "needs_review": True,
    }
    md = (f"- **Service:** `{XSS_IMG}`\n- **Alert:** `a`\n"
          "- **Generated:** 2026-07-20 10:00 UTC\n")
    _write_report(tmp_path, "inv-cafe01", payload, md)
    invs = cdata.load_investigations(tmp_path)
    page = render.render_page(invs, cdata.compute_stats(invs))
    assert "<img src=x" not in page
    assert "<script>window.__pwned=2" not in page
    assert "ARGUS" in page  # wordmark present


def test_empty_state_when_no_reports(tmp_path):
    invs = cdata.load_investigations(tmp_path)
    assert invs == []
    page = render.render_page(invs, cdata.compute_stats(invs))
    assert "No investigations yet" in page
    assert "argus investigate --replay fixtures/incident-1" in page


def test_invalid_id_rejected_by_handler_regex():
    from argus.console.server import _ID_RE
    assert _ID_RE.match("inv-fcdb95f553")
    assert not _ID_RE.match("../../etc/passwd")
    assert not _ID_RE.match("inv-<script>")
