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
