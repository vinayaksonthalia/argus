"""HTML rendering for the ARGUS Investigations Console.

This is the security boundary. Every value that originates from telemetry
(titles, root causes, log signatures, hypothesis text, service names, …) is
UNTRUSTED and must pass through ``esc()`` before it lands in markup, and
through ``safe_url()`` before it lands in an ``href``. GLASSPANE's audit found
a real XSS in exactly this render-telemetry-into-a-page pattern; the console
renders every dynamic value server-side as escaped text so the browser never
sees an un-escaped byte. ``tests/test_console.py`` proves injected
``<script>`` / ``<img onerror>`` payloads render inert.
"""

from __future__ import annotations

from html import escape

import re

from .data import Investigation, Stats, default_selection

ACCENT = "#8B5CF6"


def esc(value: object) -> str:
    """Escape any value for safe HTML text/attribute context."""
    return escape("" if value is None else str(value), quote=True)


def safe_url(url: str) -> str:
    """Only emit http(s) URLs; anything else (javascript:, data:) is dropped.

    The URL text is telemetry-derived, so an attacker could craft a
    ``javascript:`` href. Whitelist the scheme, then escape for the attribute.
    """
    u = (url or "").strip()
    if u.lower().startswith(("http://", "https://")):
        return esc(u)
    return ""


_BADGE_CLASS = {
    "VERIFIED": "badge-verified",
    "NEEDS REVIEW": "badge-review",
    "DEGRADED": "badge-degraded",
}


def _badge(status: str) -> str:
    cls = _BADGE_CLASS.get(status, "badge-review")
    return f'<span class="badge {cls}">{esc(status)}</span>'


def render_row(inv: Investigation, is_default: bool = False) -> str:
    """One row in the left investigations rail.

    ``is_default`` marks the row the console opens on (see
    ``data.default_selection``). The rule is evaluated server-side and carried
    as an attribute so the client never has to re-derive it.
    """
    conf = f"{round(inv.confidence * 100)}%"
    usd = f"${inv.cost.usd:.4f}" if inv.cost.usd else "—"
    # Lower-cased haystack so the client-side filter never has to touch the DOM
    # text (and so it matches on id/service/alert, not on rendered chrome).
    haystack = f"{inv.service} {inv.alert} {inv.id}".lower()
    # Why this row is the one the console opened on. A title/aria note rather
    # than a visible ribbon: it answers the question if you ask it, and adds no
    # chrome to a rail that is already dense.
    if is_default:
        why = (
            "Opened by default — highest-confidence verified investigation"
            if inv.status == "VERIFIED"
            else "Opened by default — most recent investigation"
        )
        default_attrs = f'data-default title="{esc(why)}" '
        default_note = f". {why}"
    else:
        default_attrs = ""
        default_note = ""
    return (
        f'<button class="row" data-id="{esc(inv.id)}" role="option" '
        f'aria-selected="false" tabindex="-1" '
        f'{default_attrs}'
        f'data-status="{esc(inv.status)}" data-search="{esc(haystack)}" '
        f'aria-label="{esc(inv.alert)} on {esc(inv.service)}, '
        f'{esc(inv.status)}, confidence {esc(conf)}{default_note}">'
        f'<div class="row-top">'
        f'<span class="row-service mono">{esc(inv.service)}</span>'
        f"{_badge(inv.status)}"
        f"</div>"
        f'<div class="row-alert">{esc(inv.alert)}</div>'
        f'<div class="row-meta">'
        f'<span class="mono">{esc(inv.id)}</span>'
        f'<span class="row-dot">·</span>'
        f"<span>{esc(inv.date_display or 'undated')}</span>"
        f"</div>"
        f'<div class="row-meta">'
        f'<span class="conf">confidence {esc(conf)}</span>'
        f'<span class="row-dot">·</span>'
        f'<span class="mono">{esc(usd)}</span>'
        f"</div>"
        f"</button>"
    )


def render_list(invs: list[Investigation]) -> str:
    if not invs:
        return (
            '<div class="rail-empty">No investigations found in this directory.</div>'
        )
    default = default_selection(invs)
    return "".join(render_row(i, is_default=i is default) for i in invs)


# Two different things happen when a hypothesis does not survive, and reading
# them as one verdict is the fastest way to read the agent wrong:
#
#   REFUTED    — the verification query RAN and the telemetry said no. That is
#                the product working, and it is why a run can be trusted.
#   UNVERIFIED — the check never ran (the SigNoz call itself failed). Nothing
#                was learned either way; it is reported rather than quietly
#                dropped, but it is not evidence against the hypothesis.
#
# So they get different marks, labels and colours: refuted keeps the muted red
# of a real negative result, unverified goes neutral grey.
_HYP_DISPLAY = {
    "CONFIRMED": ("✓", "hyp-confirmed", "CONFIRMED"),
    "REFUTED": ("✗", "hyp-refuted", "REFUTED"),
    "ERROR": ("?", "hyp-unverified", "UNVERIFIED · CHECK DID NOT RUN"),
}


def _hyp_card(h) -> str:
    mark, cls, label = _HYP_DISPLAY.get(
        h.verdict, ("·", "hyp-unverified", h.verdict)
    )
    detail = (
        f'<div class="hyp-detail">{esc(h.detail)}</div>' if h.detail else ""
    )
    return (
        f'<div class="hyp {cls}">'
        f'<div class="hyp-head"><span class="hyp-mark">{esc(mark)}</span>'
        f'<span class="hyp-verdict">{esc(label)}</span></div>'
        f'<div class="hyp-text">{esc(h.text)}</div>'
        f"{detail}"
        f"</div>"
    )


def _origin(url: str) -> str:
    """'http://host:8080/trace/x?y' -> 'http://host:8080' (already-escaped input)."""
    parts = url.split("/", 3)
    return "/".join(parts[:3]) if len(parts) >= 3 else url


def _evidence_item(ev) -> str:
    url = safe_url(ev.url)
    if url:
        # These links point at whichever SigNoz recorded the incident. Say so,
        # so a reader browsing someone else's RCA isn't surprised by a dead link.
        hint = f"Deep-links resolve on your own SigNoz instance ({_origin(url)})"
        link = (
            f'<a class="ev-link" title="{hint}" href="{url}" target="_blank" '
            f'rel="noopener noreferrer">view in SigNoz ↗</a>'
        )
    else:
        link = ""
    return f'<li class="ev"><span class="ev-text">{esc(ev.text)}</span>{link}</li>'


def render_detail(inv: Investigation) -> str:
    conf_pct = round(inv.confidence * 100)
    badge = _badge(inv.status)

    timeline_html = "".join(
        f'<li class="tl-item"><span class="tl-dot"></span>'
        f'<span class="tl-text">{esc(t)}</span></li>'
        for t in inv.timeline
    ) or '<li class="tl-item muted">No timeline recorded.</li>'

    hyp_html = "".join(_hyp_card(h) for h in inv.hypotheses) or (
        '<div class="muted">No hypotheses recorded.</div>'
    )

    evidence_html = "".join(_evidence_item(e) for e in inv.evidence) or (
        '<li class="ev muted">No evidence bullets recorded.</li>'
    )

    similar_html = ""
    if inv.similar:
        items = "".join(f'<li class="sim">{esc(s)}</li>' for s in inv.similar)
        similar_html = (
            '<section class="card"><h3>Similar past incidents '
            '<span class="chip">ARGUS memory</span></h3>'
            f'<ul class="sim-list">{items}</ul></section>'
        )

    extra_html = ""
    if inv.extra_links:
        rows = []
        for e in inv.extra_links:
            url = safe_url(e.url)
            label = esc(e.text)
            if url:
                rows.append(
                    f'<li><a href="{url}" target="_blank" '
                    f'rel="noopener noreferrer">{label} ↗</a></li>'
                )
            else:
                rows.append(f"<li>{label}</li>")
        extra_html = (
            '<section class="card"><h3>Actions taken</h3>'
            f'<ul class="link-list">{"".join(rows)}</ul></section>'
        )

    c = inv.cost
    cost_cells = "".join(
        f'<div class="cost-cell"><div class="cost-val mono">{esc(v)}</div>'
        f'<div class="cost-label">{esc(l)}</div></div>'
        for v, l in [
            (c.model or "—", "model"),
            (f"{c.tokens_in:,} / {c.tokens_out:,}", "tokens in / out"),
            (f"${c.usd:.4f}" if c.usd else "$0.00", "est. cost"),
            (c.query_stats or "—", "SigNoz query footprint"),
        ]
    )

    review_banner = ""
    if inv.status != "VERIFIED":
        why = (
            "all hypotheses refuted — evidence-only report"
            if inv.degraded
            else f"confidence {conf_pct}% is below the 75% verification threshold"
        )
        review_banner = (
            f'<div class="review-banner review-{"degraded" if inv.degraded else "review"}">'
            f"⚠ Flagged for human review — {esc(why)}.</div>"
        )

    return f"""
<article class="detail">
  <header class="verdict">
    <div class="verdict-top">
      <div class="verdict-badges">{badge}
        <span class="conf-ring" style="--pct:{conf_pct}">
          <span class="conf-num">{conf_pct}%</span>
        </span>
      </div>
      <div class="verdict-id mono">{esc(inv.id)}</div>
    </div>
    <h1>{esc(inv.title)}</h1>
    <div class="verdict-meta">
      <span class="mono">{esc(inv.service)}</span>
      <span class="row-dot">·</span>
      <span>{esc(inv.alert)}</span>
      <span class="row-dot">·</span>
      <span>{esc(inv.date_display or 'undated')}</span>
    </div>
  </header>

  {review_banner}

  <section class="card">
    <h3>Root cause</h3>
    <p class="root-cause">{esc(inv.root_cause) or '<span class="muted">Not determined.</span>'}</p>
  </section>

  <section class="card">
    <h3>Impact</h3>
    <p class="impact">{esc(inv.impact) or '<span class="muted">No impact metrics recorded.</span>'}</p>
  </section>

  <section class="card">
    <h3>Timeline</h3>
    <ul class="timeline">{timeline_html}</ul>
  </section>

  <section class="card" id="hypotheses">
    <h3>Hypotheses <span class="chip">verified against telemetry</span></h3>
    <div class="hyp-list">{hyp_html}</div>
  </section>

  <section class="card">
    <h3>Evidence <span class="chip">deep-links into SigNoz</span></h3>
    <ul class="ev-list">{evidence_html}</ul>
  </section>

  {similar_html}
  {extra_html}

  <footer class="cost-footer">
    <div class="cost-title">Investigation cost</div>
    <div class="cost-grid">{cost_cells}</div>
  </footer>
</article>
"""


def render_empty_detail(has_any: bool) -> str:
    """The main-pane empty state (design-system rule §3.1)."""
    if has_any:
        return (
            '<div class="pane-empty">'
            '<div class="pane-empty-icon">◎</div>'
            "<p>Select an investigation to view its full RCA.</p>"
            "</div>"
        )
    return (
        '<div class="pane-empty">'
        '<div class="pane-empty-icon">◎</div>'
        "<p><strong>No investigations yet.</strong></p>"
        '<p class="muted">Replay one to see the console populate:</p>'
        '<pre class="empty-cmd mono">uv run argus investigate --replay fixtures/incident-1</pre>'
        "</div>"
    )


_FILTERS = ("All", "VERIFIED", "NEEDS REVIEW", "DEGRADED")
_FILTER_LABELS = {
    "All": "All",
    "VERIFIED": "Verified",
    "NEEDS REVIEW": "Review",
    "DEGRADED": "Degraded",
}


def render_filters(invs: list[Investigation]) -> str:
    """Search box + status chips. Twenty rows is already too many to scan."""
    counts = {"All": len(invs)}
    for key in _FILTERS[1:]:
        counts[key] = sum(1 for i in invs if i.status == key)
    chips = "".join(
        f'<button class="chip-filter{" active" if key == "All" else ""}" '
        f'data-filter="{esc(key)}" aria-pressed="{"true" if key == "All" else "false"}">'
        f'{esc(_FILTER_LABELS[key])}'
        f'<span class="chip-count mono">{counts[key]}</span></button>'
        for key in _FILTERS
        if key == "All" or counts[key]
    )
    return (
        '<div class="rail-toolbar">'
        '<input id="filter" class="filter-input" type="search" autocomplete="off" '
        'placeholder="Filter by service, alert, or id…  (press /)" '
        'aria-label="Filter investigations">'
        f'<div class="chip-row" role="group" aria-label="Filter by status">{chips}</div>'
        "</div>"
    )


REPO_URL = "https://github.com/vinayaksonthalia/argus"

# The brand mark from assets/brand/icon.svg, inlined so the published bundle
# stays a self-contained directory of HTML — no image requests, nothing to copy
# alongside the export, nothing to 404.
_HERO_MARK = (
    '<svg class="hero-mark" viewBox="0 0 64 64" fill="none" aria-hidden="true" '
    'xmlns="http://www.w3.org/2000/svg">'
    '<defs><linearGradient id="argus-sweep" x1="30.4" y1="26" x2="37.1" y2="28.4" '
    'gradientUnits="userSpaceOnUse">'
    '<stop offset="0" stop-color="#8B5CF6" stop-opacity="0"/>'
    '<stop offset="1" stop-color="#8B5CF6" stop-opacity=".8"/>'
    "</linearGradient></defs>"
    '<g stroke="#8B5CF6" fill="none" stroke-linecap="round" stroke-linejoin="round">'
    '<path d="M32 12.5 A19.5 19.5 0 0 1 51.5 32" stroke-width="2.5" opacity=".34"/>'
    '<path d="M32 51.5 A19.5 19.5 0 0 1 12.5 32" stroke-width="2.5" opacity=".34"/>'
    '<path d="M8 32 C18 18 46 18 56 32 C46 46 18 46 8 32 Z" stroke-width="4"/>'
    '<circle cx="32" cy="32" r="8" stroke-width="3.5"/></g>'
    '<path d="M32 32 L30.4 26.0 A6.2 6.2 0 0 1 37.1 28.44 Z" fill="url(#argus-sweep)"/>'
    '<path d="M32 32 L37.1 28.44" stroke="#8B5CF6" stroke-width="2" stroke-linecap="round"/>'
    '<circle cx="32" cy="32" r="2.6" fill="#8B5CF6"/></svg>'
)

# One line of purpose. It has to answer "what am I looking at?" on its own,
# because it is the only prose in the band: the typed tape above it is the
# demonstration and the tour below it is the long version.
_CASE_WHAT = (
    "An autonomous AI SRE for self-hosted SigNoz — it investigates the alert "
    "alone, checks every hypothesis against your telemetry, and refuses to "
    "report what it cannot prove."
)

# The tape: the three lines the run wrote about itself, in the order it wrote
# them. Order is the information here — the alert, the agent waking up, the
# check that passed — so the elapsed offset is the structural device rather
# than an ornamental 01 / 02 / 03.
_TAPE_MARKS = (
    ("started firing", "fired"),
    ("investigation", "began"),
    ("hypothesis CONFIRMED", "confirmed"),
)

_RE_TL_SPLIT = re.compile(r"^(\d{2}:\d{2}:\d{2}) UTC\s+[—-]\s+(.*)$")

_TAPE_MAX = 84


def _clip(text: str, limit: int = _TAPE_MAX) -> str:
    """Cut a telemetry line on a word boundary so the tape sets at one width."""
    text = text.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,.;:—-")
    return f"{cut}…"


def _case_tape(inv: Investigation | None) -> list[dict]:
    """The typed case-file lines, read off the run's own timeline.

    Nothing here is hand-written: if a report has no clock-stamped timeline,
    the tape is empty and the band drops it rather than inventing a story.
    """
    if inv is None:
        return []
    stamped = []
    for entry in inv.timeline:
        m = _RE_TL_SPLIT.match(entry.strip())
        if m:
            stamped.append((m.group(1), m.group(2), _tl_seconds(entry)))
    lines: list[dict] = []
    used: set[int] = set()
    for needle, kind in _TAPE_MARKS:
        for i, (clock, text, secs) in enumerate(stamped):
            if i in used or needle not in text:
                continue
            used.add(i)
            lines.append({"clock": clock, "text": _clip(text), "kind": kind,
                          "secs": secs})
            break
    if not lines or lines[0]["secs"] is None:
        return lines
    base = lines[0]["secs"]
    # The first line IS the zero, so it carries no offset — "+0s" would be the
    # one label on the page that tells a reader nothing.
    for line in lines[1:]:
        line["offset"] = (
            f"+{line['secs'] - base}s" if line["secs"] is not None else ""
        )
    return lines


def _set_line(invs: list[Investigation], stats: Stats) -> tuple[str, str, str]:
    """`20 investigations recorded here · 1 verified · $0.94`, off the corpus.

    One small mono line carries every number in the band — and "recorded here"
    is what tells a stranger the page is a record rather than a pitch.
    """
    n_verified = sum(1 for i in invs if i.status == "VERIFIED")
    noun = "investigation" if stats.total == 1 else "investigations"
    return (
        f"{stats.total} {noun} recorded here",
        f"{n_verified} verified",
        f"${stats.total_usd:.2f}",
    )


def render_hero(invs: list[Investigation], stats: Stats) -> str:
    """The case-file band for the published static export.

    The served console is a working tool — an operator who typed ``argus
    console`` does not need to be sold the product. The published bundle is the
    opposite: it is the first thing a stranger sees. So it opens the way the
    incident opened: the run's own timeline types itself out, the elapsed time
    between the alert and the confirmed hypothesis becomes the headline, and
    two plain sentences say what ARGUS is and what this page is.

    Every string below is read off the loaded corpus. There is no hand-written
    number in this band, so it cannot drift from the reports underneath it.
    """
    inv = default_selection(invs)
    tape = _case_tape(inv)
    lines = "".join(
        f'<p class="case-line case-{esc(line["kind"])}">'
        f'<span class="case-clock mono">{esc(line["clock"])}</span>'
        f'<span class="case-text mono" data-type>{esc(line["text"])}</span>'
        f'<span class="case-off mono" aria-hidden="true">'
        f'{esc(line.get("offset", ""))}</span></p>'
        for line in tape
    )
    elapsed = _time_to_verdict(inv) if inv else None
    thesis = (
        f"{elapsed} seconds later, the postmortem existed."
        if elapsed is not None
        else "The postmortem was already written."
    )
    total, verified, spend = _set_line(invs, stats)
    dot = '<span class="case-dot" aria-hidden="true">&middot;</span>'
    set_html = (
        f'<p class="case-set mono">{esc(total)}{dot}'
        f'<span class="case-verified">{esc(verified)}</span>{dot}'
        f'{esc(spend)}</p>'
    )
    prompt_html = (
        '<button class="case-prompt mono" id="tour-start" type="button" '
        'aria-haspopup="dialog">'
        '<span class="case-caret" aria-hidden="true">&gt;</span>'
        'take the 60-second tour</button>'
    )
    tape_html = (
        f'<div class="case-tape" id="case-tape" aria-label="Investigation '
        f'timeline, replayed">{lines}</div>'
        if lines
        else ""
    )
    return f"""<header class="case">
  <div class="case-grid">
    <div class="case-main">
      {tape_html}
      <h1 class="case-thesis">{esc(thesis)}</h1>
      <p class="case-say">{esc(_CASE_WHAT)}</p>
      <div class="case-act">{prompt_html}{set_html}</div>
    </div>
    <aside class="case-side">
      <div class="case-brand">{_HERO_MARK}<span class="case-word">ARGUS</span>
        <button class="case-theme mono" id="theme-toggle" type="button"
                aria-label="Switch to the paper theme">paper</button></div>
      <a class="case-repo mono" href="{safe_url(REPO_URL)}" target="_blank"
         rel="noopener noreferrer">run it yourself &rarr;</a>
    </aside>
  </div>
</header>"""


# The family bar: the same block, in the same order, with the same per-tool
# accents on all three published demo pages. It ships only with the landing
# hero — `argus console` is a working tool, not a place to cross-sell.
_FAMILY = """<div class="family">
  <p class="fam-row">
    <span class="fam fam-argus" aria-current="page">ARGUS</span>
    <span class="fam-sep" aria-hidden="true">&middot;</span>
    <a class="fam fam-glasspane"
       href="https://vinayaksonthalia.github.io/glasspane/">GLASSPANE</a>
    <span class="fam-sep" aria-hidden="true">&middot;</span>
    <a class="fam fam-telelens"
       href="https://vinayaksonthalia.github.io/telelens/">TELELENS</a>
  </p>
  <p class="fam-tag">Three tools for self-hosted SigNoz &mdash; investigate the
    incident, watch the real browser, price the waste.</p>
</div>"""


# --------------------------------------------------------------------------
# The guided tour (published static export only).
#
# The console shows a stranger twenty investigations and never says what
# happened. This walks them through one real run — the same run the console
# opens on — and says it out loud: an alert fired, nobody typed anything, the
# agent queried the telemetry, most of its guesses died, one survived a check.
#
# Every number below is READ OFF the loaded corpus. There is no hand-written
# figure in this file, so the copy cannot drift from the reports the way a
# hand-maintained script would. Steps whose numbers a corpus can't support are
# simply phrased without them.
# --------------------------------------------------------------------------

_RE_TL_TIME = re.compile(r"^(\d{2}):(\d{2}):(\d{2}) UTC")


def _tl_seconds(entry: str) -> int | None:
    m = _RE_TL_TIME.match(entry.strip())
    if not m:
        return None
    h, mi, s = (int(g) for g in m.groups())
    return h * 3600 + mi * 60 + s


def _time_to_verdict(inv: Investigation) -> int | None:
    """Seconds between 'alert started firing' and 'hypothesis CONFIRMED'.

    Both lines are written by ARGUS into the report's own timeline, so this is
    the run's measured latency, not a stopwatch held over the demo. Returns
    ``None`` (and the copy drops the claim) if either line is absent or the
    pair straddles midnight.
    """
    fired = confirmed = None
    for t in inv.timeline:
        secs = _tl_seconds(t)
        if secs is None:
            continue
        if fired is None and "started firing" in t:
            fired = secs
        if "hypothesis CONFIRMED" in t:
            confirmed = secs
    if fired is None or confirmed is None:
        return None
    delta = confirmed - fired
    return delta if 0 < delta < 3600 else None


_RE_VERIFIED_NOTE = re.compile(r"\(verified:\s*(.+?)\)")


def _verified_note(inv: Investigation) -> str:
    """The '(verified: …)' clause ARGUS appends once a check actually passed.

    ``data._parse_hypotheses`` only lifts this into ``Hypothesis.detail`` when it
    sits at the very end of the root cause, and incident-memory context is often
    appended after it — so read it from the root cause directly.
    """
    m = _RE_VERIFIED_NOTE.search(inv.root_cause or "")
    return m.group(1).strip() if m else ""


def _headline_claim(inv: Investigation) -> str:
    """The confirmed hypothesis, cut at the seam before its reasoning."""
    for h in inv.hypotheses:
        if h.verdict == "CONFIRMED":
            return h.text.split(" — ")[0].strip()
    return ""


def _join_clauses(parts: list[str]) -> str:
    if len(parts) <= 1:
        return parts[0] if parts else ""
    return f"{', '.join(parts[:-1])} and {parts[-1]}"


def _tour_steps(invs: list[Investigation], stats: Stats) -> list[dict]:
    """Six steps over the run the console opens on, all numbers from the corpus."""
    inv = default_selection(invs)
    if inv is None:
        return []

    counts = {"CONFIRMED": 0, "REFUTED": 0, "ERROR": 0}
    for h in inv.hypotheses:
        counts[h.verdict] = counts.get(h.verdict, 0) + 1
    n_hyp = len(inv.hypotheses)
    n_conf, n_ref, n_err = counts["CONFIRMED"], counts["REFUTED"], counts["ERROR"]
    conf_pct = round(inv.confidence * 100)
    check = _verified_note(inv) or next(
        (h.detail for h in inv.hypotheses if h.verdict == "CONFIRMED" and h.detail),
        "",
    )
    claim = _headline_claim(inv)
    secs = _time_to_verdict(inv)
    n_ev = len(inv.evidence)
    n_linked = sum(1 for e in inv.evidence if safe_url(e.url))
    c = inv.cost

    # ---- 1: the alert ----------------------------------------------------
    when = f" at {inv.date_display}" if inv.date_display else ""
    if secs is not None:
        opened = (
            f"took the webhook, opened {inv.id}, and had a verified answer "
            f"{secs} seconds later"
        )
    else:
        opened = f"took the webhook and opened {inv.id} on its own"
    s1 = {
        "target": ".verdict",
        "title": "A real alert fired. Nobody typed anything.",
        "body": [
            f"“{inv.alert}” fired on service {inv.service}{when}. "
            f"ARGUS {opened}.",
            "No prompt, no operator, no runbook. Everything on this page is "
            "that run's own output, replayed from the report it wrote.",
        ],
    }

    # ---- 2: the rail -----------------------------------------------------
    tally = [
        f"{n} {label}"
        for label, n in (
            ("VERIFIED", sum(1 for i in invs if i.status == "VERIFIED")),
            ("NEEDS REVIEW", sum(1 for i in invs if i.status == "NEEDS REVIEW")),
            ("DEGRADED", sum(1 for i in invs if i.status == "DEGRADED")),
        )
        if n
    ]
    s2 = {
        "target": ".rail-col",
        "title": (
            f"{stats.total} investigations, badged honestly."
            if stats.total != 1
            else "One investigation, badged honestly."
        ),
        "body": [
            f"The rail lists every run recorded here: {_join_clauses(tally)}.",
            "A run only earns VERIFIED when a hypothesis survives a query "
            "against real telemetry and confidence clears 75%. The rest keep "
            "a badge that admits it.",
        ],
    }

    # ---- 3: the verified root cause --------------------------------------
    proof = (
        f"It ran one more query back at SigNoz to check — {check} — and only "
        f"then wrote the finding down, at {conf_pct}% confidence."
        if check
        else f"It recorded the finding at {conf_pct}% confidence."
    )
    s3 = {
        "target": ".root-cause",
        "title": "The root cause — and the query that proved it.",
        "body": [
            f"ARGUS pulled the metrics, the exemplar traces and the logs, then "
            f"named it: “{claim}”" if claim else
            "ARGUS pulled the metrics, the exemplar traces and the logs, then "
            "named the cause.",
            f"It did not stop at plausible. {proof}",
        ],
    }

    # ---- 4: the hypotheses -----------------------------------------------
    was = lambda n: "was" if n == 1 else "were"  # noqa: E731
    fates = []
    if n_conf:
        fates.append(f"{n_conf} {was(n_conf)} confirmed against the data.")
    if n_ref:
        fates.append(
            f"{n_ref} {was(n_ref)} refuted: the verification query came back "
            f"with no matching rows."
        )
    if n_err:
        fates.append(
            f"{n_err} could not be verified at all, because the check itself "
            f"failed to run — and {'that is' if n_err == 1 else 'those are'} "
            f"reported too, not quietly dropped."
        )
    s4 = {
        "target": "#hypotheses",
        "title": (
            f"{n_hyp} hypotheses were tested. {n_conf} survived."
            if n_hyp
            else "Every hypothesis is shown, whatever happened to it."
        ),
        "body": [
            " ".join(fates) if fates else
            "Each hypothesis is listed with the verdict its check returned.",
            "All of them stay on the page, each with the reason it died. An "
            "agent that hid its failures could show you one confident "
            "paragraph instead. This one refuses to bluff.",
        ],
    }

    # ---- 5: the evidence -------------------------------------------------
    s5 = {
        "target": ".ev-list",
        "title": f"{n_ev} pieces of evidence, and you can click through to each one."
        if n_ev != 1 else "One piece of evidence, and you can click through to it.",
        "body": [
            f"Metric deltas, exemplar traces with span ids, novel log "
            f"signatures — {n_linked} of the {n_ev} bullets deep-link straight "
            f"into the SigNoz view that produced them."
            if n_linked else
            "Metric deltas, exemplar traces and log signatures, each written "
            "down as ARGUS read it.",
            "Nothing here asks you to take a summary on faith. (The links "
            "resolve on the SigNoz instance that recorded the incident, not "
            "on this static page.)",
        ],
    }

    # ---- 6: the cost, and the closing honesty line -----------------------
    spend = f"${c.usd:.4f}" if c.usd else "almost nothing"
    calls = (
        f"{c.llm_calls} LLM call{'' if c.llm_calls == 1 else 's'} on {c.model}"
        if c.llm_calls and c.model
        else (c.model or "One model call")
    )
    tokens = (
        f", {c.tokens_in:,} tokens in / {c.tokens_out:,} out"
        if c.tokens_in or c.tokens_out
        else ""
    )
    queries = f", plus {c.query_stats}" if c.query_stats else ""
    s6 = {
        "target": ".cost-footer",
        "title": f"This entire investigation cost {spend}.",
        "body": [
            f"{calls}{tokens}{queries}. Printed on every report, because an "
            f"agent you cannot budget for is an agent you cannot run.",
            f"All {stats.total} runs together came to ${stats.total_usd:.2f}, "
            f"and {stats.verified} of {stats.total} cleared verification. That "
            f"ratio is on the page rather than hidden — the honesty is the "
            f"feature.",
        ],
        "link": REPO_URL,
        "link_text": "Read the source on GitHub",
    }

    return [s1, s2, s3, s4, s5, s6]


def render_tour(invs: list[Investigation], stats: Stats) -> str:
    """The tour's DOM: a scrim, a spotlight, a card, and the escaped step copy.

    The step text is rendered here as ordinary escaped HTML in a hidden block
    and cloned into the card by the client. No copy is interpolated into a
    JavaScript string literal — same rule as the rest of this file.
    """
    steps = _tour_steps(invs, stats)
    if not steps:
        return ""
    inv = default_selection(invs)
    items = []
    for i, step in enumerate(steps, 1):
        paras = "".join(f"<p>{esc(p)}</p>" for p in step["body"])
        link = ""
        url = safe_url(step.get("link", ""))
        if url:
            link = (
                f'<p class="tour-link"><a href="{url}" target="_blank" '
                f'rel="noopener noreferrer">{esc(step["link_text"])} &rarr;</a></p>'
            )
        items.append(
            f'<div class="tour-step" data-target="{esc(step["target"])}" '
            f'data-title="{esc(step["title"])}" data-step="{i}">{paras}{link}</div>'
        )
    return (
        f'<div id="tour-steps" data-inv="{esc(inv.id if inv else "")}" hidden>'
        f'{"".join(items)}</div>'
        '<div class="tour-root" id="tour" hidden>'
        '<div class="tour-scrim"></div>'
        '<div class="tour-spot" id="tour-spot" aria-hidden="true"></div>'
        '<div class="tour-card" id="tour-card" role="dialog" aria-modal="true" '
        'aria-labelledby="tour-heading">'
        '<div class="tour-head">'
        '<span class="tour-count mono" id="tour-count"></span>'
        '<button class="tour-x" id="tour-close" type="button" '
        'aria-label="End the tour (Esc)">&#10005;</button>'
        "</div>"
        '<h2 class="tour-heading" id="tour-heading"></h2>'
        '<div class="tour-body" id="tour-body"></div>'
        '<div class="tour-nav">'
        '<button class="tour-btn" id="tour-back" type="button">Back</button>'
        '<button class="tour-btn tour-btn-next" id="tour-next" type="button">'
        "Next</button>"
        "</div></div></div>"
    )


def _topbar(stats: Stats) -> str:
    stats_strip = (
        f'<div class="stat"><span class="stat-val mono">{stats.total}</span>'
        f'<span class="stat-label">investigations</span></div>'
        f'<div class="stat"><span class="stat-val mono">{stats.verified_pct}%</span>'
        f'<span class="stat-label">verified</span></div>'
        f'<div class="stat"><span class="stat-val mono">${stats.total_usd:.2f}</span>'
        f'<span class="stat-label">total spend</span></div>'
    )
    return f"""<header class="topbar">
  <div class="wordmark">
    <span class="mark" aria-hidden="true">◇</span>
    <span class="word">ARGUS</span>
    <span class="sub">Investigations Console</span>
  </div>
  <div class="stats-strip">{stats_strip}</div>
</header>"""


def render_page(invs: list[Investigation], stats: Stats, hero: bool = False) -> str:
    """The full single-page shell (server-rendered list + client detail fetch).

    ``hero=True`` swaps the working-tool topbar for the landing band used by the
    published static export (see ``render_hero``).
    """
    list_html = render_list(invs)
    empty_detail = render_empty_detail(bool(invs))
    # The tour, its CSS and its JS ship only with the published bundle — the
    # served console is a working tool, and a stranger's walkthrough is chrome
    # an operator never asked for. Appending rather than interleaving keeps the
    # served page byte-for-byte what it was.
    return _PAGE_TEMPLATE.format(
        css=_CSS + (_TOUR_CSS + _CASE_CSS if hero else ""),
        accent=ACCENT,
        # `data-theme="auto"` follows the OS until the band's own toggle pins a
        # side; the light palette is a plain attribute swap, so the page works
        # with JavaScript off. The served console never carries either.
        body_class=' class="has-hero" data-theme="auto"' if hero else "",
        header=render_hero(invs, stats) if hero else _topbar(stats),
        family=_FAMILY if hero else "",
        filters=render_filters(invs) if invs else "",
        list_html=list_html,
        empty_detail=empty_detail,
        tour=render_tour(invs, stats) if hero else "",
        js=_JS + (_TOUR_JS + _CASE_JS if hero else ""),
    )


# --------------------------------------------------------------------------
# Static shell. No data is interpolated into JS; the browser fetches escaped
# HTML fragments from /api/detail/<id> and injects them. Everything dynamic is
# escaped server-side before it ever reaches this template.
# --------------------------------------------------------------------------

_PAGE_TEMPLATE = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ARGUS — Investigations Console</title>
<style>{css}</style>
</head>
<body{body_class}>
{header}
<main class="layout">
  <aside class="rail-col">
    {filters}
    <div class="rail" id="rail" role="listbox" aria-label="Investigations" tabindex="0">
      {list_html}
    </div>
    <div class="rail-noresults" id="noresults" hidden>No investigations match.</div>
  </aside>
  <section class="pane" id="pane">
    {empty_detail}
  </section>
  {family}
</main>{tour}
<script>{js}</script>
</body>
</html>
"""

_JS = r"""
(function () {
  var rail = document.getElementById('rail');
  var pane = document.getElementById('pane');
  var current = null;

  function skeleton() {
    pane.innerHTML =
      '<div class="skeleton">' +
      '<div class="sk sk-title"></div><div class="sk sk-line"></div>' +
      '<div class="sk sk-card"></div><div class="sk sk-card"></div></div>';
  }

  function errorState(id, msg) {
    var box = document.createElement('div');
    box.className = 'pane-error';
    var h = document.createElement('strong');
    h.textContent = "Couldn't load this investigation";
    var p = document.createElement('p');
    p.textContent = msg;
    var btn = document.createElement('button');
    btn.className = 'retry';
    btn.textContent = 'Retry';
    btn.onclick = function () { select(id); };
    box.appendChild(h); box.appendChild(p); box.appendChild(btn);
    pane.innerHTML = '';
    pane.appendChild(box);
  }

  function select(id, block) {
    if (!id) return;
    current = id;
    [].forEach.call(rail.querySelectorAll('.row'), function (r) {
      var on = r.getAttribute('data-id') === id;
      r.classList.toggle('active', on);
      r.setAttribute('aria-selected', on ? 'true' : 'false');
      r.tabIndex = on ? 0 : -1;
      // 'nearest' keeps j/k walking from jumping the list around; the initial
      // landing row centres instead, so a rail that opens part-scrolled reads
      // as deliberate rather than as a stray scroll position.
      if (on && r.scrollIntoView) r.scrollIntoView({block: block || 'nearest'});
    });
    skeleton();
    fetch('api/detail/' + encodeURIComponent(id))
      .then(function (res) {
        if (!res.ok) throw new Error('HTTP ' + res.status);
        return res.text();
      })
      .then(function (html) {
        if (current !== id) return; // a newer click won
        pane.innerHTML = html; // server-escaped fragment
        pane.scrollTop = 0;
        if (location.hash.slice(1) !== id) {
          history.replaceState(null, '', '#' + id);
        }
      })
      .catch(function (e) { errorState(id, String(e.message || e)); });
  }

  rail.addEventListener('click', function (e) {
    var row = e.target.closest('.row');
    if (row) select(row.getAttribute('data-id'));
  });

  window.addEventListener('hashchange', function () {
    var id = location.hash.slice(1);
    if (id && id !== current) select(id);
  });

  // ---- filtering: free-text over service/alert/id + a status chip ----------
  var input = document.getElementById('filter');
  var noresults = document.getElementById('noresults');
  var chips = [].slice.call(document.querySelectorAll('.chip-filter'));
  var status = 'All';

  function visibleRows() {
    return [].filter.call(rail.querySelectorAll('.row'), function (r) {
      return !r.hidden;
    });
  }

  function applyFilter() {
    var q = (input && input.value || '').trim().toLowerCase();
    var shown = 0;
    [].forEach.call(rail.querySelectorAll('.row'), function (r) {
      var okText = !q || r.getAttribute('data-search').indexOf(q) !== -1;
      var okStatus = status === 'All' || r.getAttribute('data-status') === status;
      r.hidden = !(okText && okStatus);
      if (!r.hidden) shown++;
    });
    if (noresults) noresults.hidden = shown !== 0;
  }

  if (input) {
    input.addEventListener('input', applyFilter);
    input.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') { input.value = ''; applyFilter(); input.blur(); }
      if (e.key === 'Enter') {
        var rows = visibleRows();
        if (rows.length) select(rows[0].getAttribute('data-id'));
      }
    });
  }

  chips.forEach(function (c) {
    c.addEventListener('click', function () {
      status = c.getAttribute('data-filter');
      chips.forEach(function (o) {
        var on = o === c;
        o.classList.toggle('active', on);
        o.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      applyFilter();
    });
  });

  // ---- keyboard: / focuses the filter, arrows / j / k walk the rail --------
  function step(delta) {
    var rows = visibleRows();
    if (!rows.length) return;
    var idx = -1;
    for (var i = 0; i < rows.length; i++) {
      if (rows[i].getAttribute('data-id') === current) { idx = i; break; }
    }
    var next = rows[Math.min(rows.length - 1, Math.max(0, idx + delta))];
    if (next) { select(next.getAttribute('data-id')); next.focus(); }
  }

  document.addEventListener('keydown', function (e) {
    var tag = (e.target.tagName || '').toLowerCase();
    var typing = tag === 'input' || tag === 'textarea';
    if (e.key === '/' && !typing) { e.preventDefault(); if (input) input.focus(); return; }
    if (typing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowDown' || e.key === 'j') { e.preventDefault(); step(1); }
    else if (e.key === 'ArrowUp' || e.key === 'k') { e.preventDefault(); step(-1); }
  });

  // ---- landing hero (published export only; absent in the served console) --
  // Sends a first-time visitor from the pitch into the actual evidence: the
  // root-cause pane of whichever run the console opened on.
  var heroScroll = document.getElementById('hero-scroll');
  if (heroScroll) {
    heroScroll.addEventListener('click', function () {
      var target = pane.querySelector('#hypotheses') || pane.querySelector('.card') || pane;
      if (target.scrollIntoView) target.scrollIntoView({behavior: 'smooth', block: 'start'});
    });
  }

  // A #inv-… deep link always wins. Otherwise open on the row the server
  // marked (highest-confidence VERIFIED run, else newest) — see
  // data.default_selection. The rail order itself is untouched by this.
  var initial = location.hash.slice(1);
  var landing = rail.querySelector('.row[data-default]') || rail.querySelector('.row');
  if (initial) select(initial, 'center');
  else if (landing) select(landing.getAttribute('data-id'), 'center');
})();
"""

_CSS = r"""
:root{
  --bg-canvas:#0A0B0D; --bg-surface:#111214; --bg-raised:#17181B;
  --hairline:rgba(255,255,255,.08); --border:rgba(255,255,255,.14);
  --text-1:#EDEDEF; --text-2:#9A9BA3; --text-3:#6C6D75;
  --accent:#8B5CF6; --accent-dim:rgba(139,92,246,.16);
  --green:#3DD68C; --amber:#F5A623; --red:#E5484D; --blue:#5B8DEF;
  --mono:"JetBrains Mono","SF Mono",ui-monospace,Menlo,Consolas,monospace;
  --sans:Inter,-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,system-ui,sans-serif;
}
*{box-sizing:border-box}
/* The rail filter hides rows via the `hidden` attribute, but `.row` sets
   display:block — a class selector outranks the UA sheet's [hidden] rule, so
   without this the rows stay visible. Keep it above every display: rule. */
[hidden]{display:none !important}
html,body{margin:0;height:100%}
body{
  background:var(--bg-canvas); color:var(--text-1);
  font-family:var(--sans); font-size:14px; line-height:1.5;
  -webkit-font-smoothing:antialiased;
}
.mono{font-family:var(--mono); font-variant-numeric:tabular-nums}

/* ---- top bar ---- */
.topbar{
  display:flex; align-items:center; justify-content:space-between;
  height:56px; padding:0 20px; border-bottom:1px solid var(--hairline);
  background:var(--bg-surface); position:sticky; top:0; z-index:10;
}
.wordmark{display:flex; align-items:baseline; gap:10px}
.wordmark .mark{color:var(--accent); font-size:18px; transform:translateY(1px)}
.wordmark .word{font-weight:600; letter-spacing:.14em; font-size:15px}
.wordmark .sub{color:var(--text-3); font-size:12px; letter-spacing:.02em}
.stats-strip{display:flex; gap:22px}
.stat{display:flex; flex-direction:column; align-items:flex-end; line-height:1.15}
.stat-val{font-size:15px; font-weight:600}
.stat-label{font-size:11px; color:var(--text-3); text-transform:uppercase; letter-spacing:.05em}

/* ---- landing hero (published static export only; replaces .topbar) ----
   Budget: one band under 120px on desktop. It introduces the product to a
   stranger and then gets out of the way — the rail and the RCA below it are
   the actual proof, and they must stay above the fold. */
.hero{
  --hero-h:112px;
  height:var(--hero-h); flex:none; box-sizing:border-box; overflow:hidden;
  padding:12px 24px 10px; border-bottom:1px solid var(--hairline);
  background:
    radial-gradient(700px 130px at 8% -40%,rgba(139,92,246,.13),transparent 70%),
    var(--bg-surface);
}
.hero-row{display:flex; align-items:center; gap:20px}
.hero-brand{display:flex; align-items:center; gap:9px; flex:none}
.hero-mark{width:26px; height:26px; display:block}
.hero-word{font-weight:600; font-size:17px; letter-spacing:.16em}
/* Three tiers, one band: wordmark (who) -> thesis (what you get) -> prop (why
   it is true). One number gets the oversized treatment; the rest stay pills. */
.hero-thesis{
  margin:7px 0 0; font-size:18px; font-weight:600; line-height:1.25;
  letter-spacing:-.018em; color:var(--text-1);
}
.hero-prop{
  margin:2px 0 0;
  font-size:12.5px; line-height:1.45; color:var(--text-2);
}
.hero-lead{
  display:flex; align-items:baseline; gap:9px; flex:none;
  padding-left:20px; border-left:1px solid var(--hairline);
}
.hero-lead b{
  font-size:32px; font-weight:600; line-height:1; letter-spacing:-.03em;
  color:var(--text-1);
}
.hero-lead .hero-chip-label{
  font-size:10.5px; color:var(--text-3); text-transform:uppercase;
  letter-spacing:.07em; line-height:1;
}
.hero-actions{display:flex; align-items:center; gap:8px; flex:none; margin-left:auto}
.hero-btn{
  display:inline-flex; align-items:center; white-space:nowrap; cursor:pointer;
  font:inherit; font-size:12.5px; font-weight:500; text-decoration:none;
  border-radius:6px; padding:7px 13px; border:1px solid transparent;
  transition:background .12s,border-color .12s,color .12s;
}
.hero-btn-primary{background:var(--accent); color:#fff}
.hero-btn-primary:hover{background:#7C4DEF}
.hero-btn-ghost{background:transparent; color:var(--text-2); border-color:var(--border)}
.hero-btn-ghost:hover{background:var(--bg-raised); color:var(--text-1)}
.hero-btn:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.hero-chips{display:flex; flex-wrap:wrap; align-items:center; gap:7px}
.hero-chip{
  display:inline-flex; align-items:baseline; gap:6px;
  border:1px solid var(--hairline); border-radius:999px; padding:2.5px 10px;
  font-size:11.5px; color:var(--text-3); background:var(--bg-canvas);
}
.hero-chip b{font-size:12.5px; font-weight:600; color:var(--text-1)}
.hero-chip-label{white-space:nowrap}

/* ---- layout ---- */
.layout{display:grid; grid-template-columns:320px 1fr; grid-template-rows:1fr auto;
  height:calc(100% - 56px)}
.has-hero .layout{height:calc(100% - 112px)}

/* ---- family bar (published export only; the same block, order and accents
   ship on all three demo pages) ---- */
.family{
  grid-column:1 / -1; flex:none; padding:11px 24px 12px;
  border-top:1px solid var(--hairline); background:var(--bg-surface);
}
.fam-row{display:flex; align-items:center; flex-wrap:wrap; gap:9px; margin:0}
.fam{font-size:12.5px; font-weight:600; letter-spacing:.14em; text-decoration:none}
a.fam:hover{text-decoration:underline; text-underline-offset:3px}
.fam-argus{color:#8B5CF6} .fam-glasspane{color:#5B8DEF} .fam-telelens{color:#2DD4BF}
[aria-current="page"].fam{border-bottom:1.5px solid currentColor; padding-bottom:1px}
.fam-sep{color:var(--text-3)}
.fam-tag{margin:5px 0 0; font-size:12px; color:var(--text-3)}
.rail-col{
  display:flex; flex-direction:column; min-height:0;
  border-right:1px solid var(--hairline); background:var(--bg-canvas);
}
.rail{overflow-y:auto; padding:8px; flex:1; min-height:0}
.rail:focus{outline:none}
.pane{overflow-y:auto; padding:28px 32px 64px}

/* ---- rail toolbar (filter + status chips) ---- */
.rail-toolbar{padding:10px 12px 8px; border-bottom:1px solid var(--hairline); flex:none}
.filter-input{
  width:100%; background:var(--bg-surface); color:var(--text-1);
  border:1px solid var(--border); border-radius:8px; padding:7px 10px;
  font:inherit; font-size:12.5px; margin-bottom:8px;
}
.filter-input::placeholder{color:var(--text-3)}
.filter-input:focus{outline:none; border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-dim)}
.filter-input::-webkit-search-cancel-button{filter:invert(.6)}
.chip-row{display:flex; flex-wrap:wrap; gap:5px}
.chip-filter{
  display:inline-flex; align-items:center; gap:4px; cursor:pointer; white-space:nowrap;
  background:transparent; color:var(--text-2); font:inherit; font-size:11px;
  border:1px solid var(--hairline); border-radius:999px; padding:3px 8px;
  transition:background .12s,border-color .12s,color .12s;
}
.chip-filter:hover{background:var(--bg-surface); color:var(--text-1)}
.chip-filter.active{background:var(--accent-dim); border-color:rgba(139,92,246,.4); color:var(--text-1)}
.chip-filter:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.chip-count{font-size:11px; color:var(--text-3)}
.chip-filter.active .chip-count{color:var(--text-2)}
.rail-noresults{padding:18px 14px; color:var(--text-3); font-size:12.5px; flex:none}

/* ---- rail rows ---- */
.row{
  display:block; width:100%; text-align:left; cursor:pointer;
  background:transparent; border:1px solid transparent; border-radius:10px;
  padding:11px 12px; margin-bottom:4px; color:inherit; font:inherit;
  transition:background .12s,border-color .12s;
}
.row:hover{background:var(--bg-surface)}
.row.active{background:var(--accent-dim); border-color:rgba(139,92,246,.4)}
.row:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.row-top{display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom:5px}
.row-service{font-size:12px; color:var(--text-2); font-weight:500}
.row-alert{font-weight:510; font-size:13.5px; margin-bottom:5px; line-height:1.35}
.row-meta{display:flex; align-items:center; gap:7px; font-size:11.5px; color:var(--text-3)}
.row-dot{color:var(--text-3)}
.conf{color:var(--text-2)}
.rail-empty{padding:24px 12px; color:var(--text-3); font-size:13px}

/* ---- badges ---- */
.badge{
  font-size:10.5px; font-weight:600; letter-spacing:.04em; text-transform:uppercase;
  padding:2.5px 8px; border-radius:999px; white-space:nowrap;
  border:1px solid transparent;
}
.badge-verified{color:var(--green); background:rgba(61,214,140,.12); border-color:rgba(61,214,140,.3)}
.badge-review{color:var(--amber); background:rgba(245,166,35,.12); border-color:rgba(245,166,35,.3)}
.badge-degraded{color:var(--red); background:rgba(229,72,77,.12); border-color:rgba(229,72,77,.3)}

/* ---- detail ---- */
.detail{max-width:900px}
.verdict{margin-bottom:22px}
.verdict-top{display:flex; align-items:center; justify-content:space-between; margin-bottom:12px}
.verdict-badges{display:flex; align-items:center; gap:14px}
.verdict-id{font-size:12px; color:var(--text-3)}
.verdict h1{font-size:24px; font-weight:600; letter-spacing:-.02em; margin:0 0 10px; line-height:1.25}
.verdict-meta{display:flex; align-items:center; gap:9px; color:var(--text-2); font-size:13px; flex-wrap:wrap}

.conf-ring{
  --pct:0; position:relative; width:44px; height:44px; border-radius:50%;
  display:grid; place-items:center;
  background:conic-gradient(var(--accent) calc(var(--pct)*1%), var(--hairline) 0);
}
.conf-ring::before{content:""; position:absolute; inset:4px; border-radius:50%; background:var(--bg-canvas)}
.conf-num{position:relative; font-size:11px; font-weight:600; font-family:var(--mono)}

.review-banner{
  padding:11px 14px; border-radius:10px; font-size:13px; margin-bottom:20px; font-weight:500;
}
.review-review{color:var(--amber); background:rgba(245,166,35,.1); border:1px solid rgba(245,166,35,.28)}
.review-degraded{color:var(--red); background:rgba(229,72,77,.1); border:1px solid rgba(229,72,77,.28)}

.card{
  background:var(--bg-surface); border:1px solid var(--hairline); border-radius:12px;
  padding:18px 20px; margin-bottom:16px;
}
.card h3{
  margin:0 0 12px; font-size:12px; text-transform:uppercase; letter-spacing:.06em;
  color:var(--text-2); font-weight:600; display:flex; align-items:center; gap:10px;
}
.chip{
  text-transform:none; letter-spacing:normal; font-weight:500; font-size:11px;
  color:var(--text-3); background:var(--bg-raised); border:1px solid var(--hairline);
  padding:1.5px 8px; border-radius:999px;
}
.root-cause{margin:0; font-size:15px; line-height:1.6}
.impact{margin:0; font-family:var(--mono); font-size:13px; color:var(--text-1); line-height:1.7}
.muted{color:var(--text-3)}

/* ---- timeline ---- */
.timeline{list-style:none; margin:0; padding:0}
.tl-item{position:relative; padding:0 0 14px 20px; font-size:13px; line-height:1.5}
.tl-item:last-child{padding-bottom:0}
.tl-dot{position:absolute; left:0; top:6px; width:8px; height:8px; border-radius:50%;
  background:var(--accent); box-shadow:0 0 0 3px var(--accent-dim)}
.timeline .tl-item:not(:last-child)::before{
  content:""; position:absolute; left:3.5px; top:12px; bottom:2px; width:1px; background:var(--hairline)}
.tl-text{color:var(--text-1)}

/* ---- hypotheses ---- */
.hyp-list{display:flex; flex-direction:column; gap:10px}
.hyp{border:1px solid var(--hairline); border-radius:10px; padding:12px 14px; border-left-width:3px}
.hyp-head{display:flex; align-items:center; gap:8px; margin-bottom:6px}
.hyp-mark{width:18px; height:18px; border-radius:50%; display:grid; place-items:center;
  font-size:12px; font-weight:700; color:#0A0B0D}
.hyp-verdict{font-size:11px; font-weight:600; letter-spacing:.05em; text-transform:uppercase}
.hyp-text{font-size:13.5px; line-height:1.5}
.hyp-detail{margin-top:7px; font-size:12px; color:var(--text-2); font-family:var(--mono); line-height:1.5}
.hyp-confirmed{border-left-color:var(--green)}
.hyp-confirmed .hyp-mark{background:var(--green)} .hyp-confirmed .hyp-verdict{color:var(--green)}
.hyp-refuted{border-left-color:var(--red); opacity:.78}
.hyp-refuted .hyp-mark{background:var(--red)} .hyp-refuted .hyp-verdict{color:var(--red)}
.hyp-refuted .hyp-text{color:var(--text-2)}
/* Neutral, not alarming: nothing was disproved here, the check just never ran.
   Quieter than REFUTED, so the eye lands on the verdicts that mean something. */
.hyp-unverified{border-left-color:var(--text-3); opacity:.88}
.hyp-unverified .hyp-mark{background:var(--text-3); color:var(--bg-canvas)}
.hyp-unverified .hyp-verdict{color:var(--text-3); letter-spacing:.06em}
.hyp-unverified .hyp-text{color:var(--text-2)}

/* ---- evidence / similar / links ---- */
.ev-list,.sim-list,.link-list{list-style:none; margin:0; padding:0}
.ev{display:flex; align-items:flex-start; justify-content:space-between; gap:14px;
  padding:9px 0; border-bottom:1px solid var(--hairline); font-size:13px; line-height:1.5}
.ev:last-child{border-bottom:none}
.ev-text{flex:1}
.ev-link,.link-list a,.sim-list a{color:var(--accent); text-decoration:none; white-space:nowrap; font-size:12.5px}
.ev-link:hover,.link-list a:hover{text-decoration:underline}
.sim{padding:9px 0; border-bottom:1px solid var(--hairline); font-size:12.5px; color:var(--text-2); line-height:1.55}
.sim:last-child{border-bottom:none}
.link-list li{padding:6px 0; font-size:13px}

/* ---- cost footer ---- */
.cost-footer{border:1px solid var(--hairline); border-radius:12px; padding:16px 20px; background:var(--bg-surface)}
.cost-title{font-size:11px; text-transform:uppercase; letter-spacing:.06em; color:var(--text-3); margin-bottom:12px}
.cost-grid{display:grid; grid-template-columns:repeat(auto-fit,minmax(150px,1fr)); gap:16px}
.cost-cell{min-width:0}
.cost-val{font-size:13px; font-weight:600; overflow-wrap:anywhere}
.cost-label{font-size:11px; color:var(--text-3); margin-top:3px}

/* ---- empty / loading / error ---- */
.pane-empty{display:flex; flex-direction:column; align-items:center; justify-content:center;
  height:100%; text-align:center; color:var(--text-2); gap:6px}
.pane-empty-icon{font-size:34px; color:var(--text-3); margin-bottom:6px}
.empty-cmd{margin-top:10px; background:var(--bg-surface); border:1px solid var(--hairline);
  border-radius:8px; padding:10px 14px; color:var(--accent); font-size:13px}
.pane-error{max-width:420px; margin:60px auto; text-align:center; color:var(--text-2);
  background:rgba(229,72,77,.08); border:1px solid rgba(229,72,77,.3); border-radius:12px; padding:24px}
.pane-error strong{color:var(--red); display:block; margin-bottom:6px}
.retry{margin-top:14px; background:var(--accent); color:#fff; border:none; border-radius:8px;
  padding:8px 16px; font:inherit; font-weight:500; cursor:pointer}
.skeleton{max-width:900px}
.sk{background:linear-gradient(90deg,var(--bg-surface) 25%,var(--bg-raised) 50%,var(--bg-surface) 75%);
  background-size:200% 100%; animation:shimmer 1.3s infinite; border-radius:8px}
.sk-title{height:28px; width:60%; margin-bottom:14px}
.sk-line{height:14px; width:40%; margin-bottom:22px}
.sk-card{height:120px; margin-bottom:16px}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}

/* scrollbars */
.rail::-webkit-scrollbar,.pane::-webkit-scrollbar{width:10px}
.rail::-webkit-scrollbar-thumb,.pane::-webkit-scrollbar-thumb{
  background:var(--border); border-radius:8px; border:3px solid var(--bg-canvas)}

/* Respect the OS "reduce motion" setting: the shimmer becomes a flat block. */
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{animation-duration:.01ms !important; animation-iteration-count:1 !important;
    transition-duration:.01ms !important; scroll-behavior:auto !important}
  .sk{background:var(--bg-surface)}
}

@media (max-width:760px){
  .layout{grid-template-columns:1fr; height:auto}
  .has-hero .layout{height:auto}
  .rail-col{border-right:none; border-bottom:1px solid var(--hairline)}
  .rail{max-height:40vh}
  .pane{padding:20px 16px 48px}
  .stats-strip{gap:14px}
  /* The band stacks and the page scrolls; a fixed height would clip it. */
  .hero{height:auto; overflow:visible; padding:16px}
  .hero-row{flex-wrap:wrap; gap:12px}
  .hero-brand{order:1}
  .hero-actions{order:2; margin-left:auto}
  .hero-lead{order:3; flex:1 1 100%; padding-left:0; border-left:none}
  .hero-lead b{font-size:38px}
  .hero-lead .hero-chip-label{max-width:none}
  .hero-chips{order:4; flex:1 1 100%}
  .hero-thesis{font-size:19px; margin-top:12px}
  .family{padding:14px 16px 16px}
}
/* Laptop widths: the band is one line of proof, so the secondary pills are the
   first thing to go rather than letting the row wrap and clip. */
@media (min-width:761px) and (max-width:1180px){
  .hero-chips{display:none}
}
"""

# --------------------------------------------------------------------------
# Tour CSS + JS. Appended to the shared sheet/script only when hero=True, so
# `argus console` renders exactly the bytes it rendered before this existed.
# --------------------------------------------------------------------------

_TOUR_CSS = r"""
/* ---- the "what am I looking at?" affordance in the landing band ---- */
.hero-btn-tour{
  background:var(--accent-dim); color:var(--text-1);
  border-color:rgba(139,92,246,.45); gap:7px;
}
.hero-btn-tour:hover{background:rgba(139,92,246,.26); border-color:var(--accent)}
.hero-btn-sub{
  font-size:10.5px; font-weight:500; color:var(--text-3);
  text-transform:uppercase; letter-spacing:.06em; white-space:nowrap;
}

/* ---- the tour itself ----
   Three layers: a scrim that swallows clicks so the page underneath can't be
   half-driven mid-tour, a spotlight box whose 9999px shadow *is* the dimming
   (one element, no four-panel maths, no seams), and the card. */
.tour-root{position:fixed; inset:0; z-index:1000}
.tour-root[hidden]{display:none !important}
.tour-scrim{position:absolute; inset:0; background:transparent}
.tour-spot{
  position:fixed; border-radius:12px; pointer-events:none;
  border:1.5px solid rgba(139,92,246,.85);
  box-shadow:0 0 0 9999px rgba(6,7,9,.74), 0 0 0 4px rgba(139,92,246,.18);
  transition:top .22s ease,left .22s ease,width .22s ease,height .22s ease;
}
.tour-spot.is-blank{border-color:transparent; box-shadow:0 0 0 9999px rgba(6,7,9,.74)}
.tour-card{
  position:fixed; width:352px; max-width:calc(100vw - 32px);
  background:var(--bg-raised); border:1px solid var(--border);
  border-radius:14px; padding:16px 18px 14px;
  box-shadow:0 18px 48px rgba(0,0,0,.55);
}
.tour-head{display:flex; align-items:center; justify-content:space-between; margin-bottom:8px}
.tour-count{font-size:11px; color:var(--text-3); letter-spacing:.08em}
.tour-x{
  background:transparent; border:none; color:var(--text-3); cursor:pointer;
  font:inherit; font-size:13px; line-height:1; padding:4px 5px; border-radius:6px;
}
.tour-x:hover{color:var(--text-1); background:var(--bg-surface)}
.tour-heading{
  margin:0 0 8px; font-size:16px; font-weight:600; line-height:1.3;
  letter-spacing:-.015em; color:var(--text-1);
}
.tour-body p{margin:0 0 9px; font-size:13px; line-height:1.55; color:var(--text-2)}
.tour-body p:last-child{margin-bottom:0}
.tour-link a{color:var(--accent); text-decoration:none; font-weight:500}
.tour-link a:hover{text-decoration:underline}
.tour-nav{display:flex; align-items:center; justify-content:flex-end; gap:8px; margin-top:14px}
.tour-btn{
  font:inherit; font-size:12.5px; font-weight:500; cursor:pointer;
  border-radius:7px; padding:7px 14px; border:1px solid var(--border);
  background:transparent; color:var(--text-2);
}
.tour-btn:hover{background:var(--bg-surface); color:var(--text-1)}
.tour-btn[disabled]{opacity:.4; cursor:default}
.tour-btn-next{background:var(--accent); border-color:var(--accent); color:#fff}
.tour-btn-next:hover{background:#7C4DEF; color:#fff}
.tour-btn:focus-visible,.tour-x:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
/* Narrow screens drop the spotlight (a cutout over a stacked, scrolling page
   lands badly) and the card becomes a bottom sheet; the step's subject just
   gets a ring so you still know what is being pointed at. */
.tour-lit{outline:2px solid var(--accent); outline-offset:3px; border-radius:10px}
@media (max-width:760px){
  .tour-spot{display:none}
  .tour-scrim{background:rgba(6,7,9,.5)}
  .tour-card{
    left:0; right:0; bottom:0; top:auto; width:auto; max-width:none;
    border-radius:16px 16px 0 0; border-bottom:none; padding:16px 18px 18px;
    max-height:72vh; overflow-y:auto;
  }
  /* Three affordances no longer fit beside the wordmark, so they take their
     own full-width row instead of pushing the band into a sideways scroll. */
  .hero-actions{
    order:2; flex:1 1 100%; margin-left:0;
    flex-wrap:wrap; justify-content:flex-start;
  }
}
/* Laptop widths: the band is one fixed-height line, so the tour button buys its
   space from its own sub-label and from "See the evidence" — which it makes
   redundant anyway, since the tour walks you into exactly that evidence. */
@media (min-width:761px) and (max-width:1180px){
  .hero-btn-sub{display:none}
  #hero-scroll{display:none}
}
@media (prefers-reduced-motion:reduce){.tour-spot{transition:none}}
"""

_TOUR_JS = r"""
(function () {
  var steps = document.getElementById('tour-steps');
  var root = document.getElementById('tour');
  var startBtn = document.getElementById('tour-start');
  if (!steps || !root || !startBtn) return;

  var items = [].slice.call(steps.querySelectorAll('.tour-step'));
  if (!items.length) return;

  var pane = document.getElementById('pane');
  var spot = document.getElementById('tour-spot');
  var card = document.getElementById('tour-card');
  var heading = document.getElementById('tour-heading');
  var body = document.getElementById('tour-body');
  var count = document.getElementById('tour-count');
  var backBtn = document.getElementById('tour-back');
  var nextBtn = document.getElementById('tour-next');
  var closeBtn = document.getElementById('tour-close');
  var idx = 0;
  var open = false;
  var lit = null;
  var opener = null;

  function narrow() {
    return window.matchMedia('(max-width: 760px)').matches;
  }

  function clearLit() {
    if (lit) { lit.classList.remove('tour-lit'); lit = null; }
  }

  function placeCard(rect) {
    if (narrow()) {
      // Bottom sheet: the stylesheet pins it to the viewport edges, so any
      // inline coordinates left over from a wider layout have to go.
      card.style.top = '';
      card.style.left = '';
      return;
    }
    var m = 16, vw = window.innerWidth, vh = window.innerHeight;
    var cw = card.offsetWidth, ch = card.offsetHeight;
    var top, left;
    if (!rect) {
      card.style.top = Math.max(m, (vh - ch) / 2) + 'px';
      card.style.left = Math.max(m, (vw - cw) / 2) + 'px';
      return;
    }
    if (rect.bottom + m + ch + m <= vh) {          // below the subject
      top = rect.bottom + m;
      left = rect.left;
    } else if (rect.top - m - ch >= m) {           // above it
      top = rect.top - m - ch;
      left = rect.left;
    } else if (rect.right + m + cw + m <= vw) {    // beside it, right
      top = rect.top;
      left = rect.right + m;
    } else if (rect.left - m - cw >= m) {          // beside it, left
      top = rect.top;
      left = rect.left - m - cw;
    } else {
      // The subject is taller and wider than any gap (a full-height card).
      // Overlap is unavoidable, so overlap the *dimmed* side — the wider of
      // the two margins — rather than sitting on the thing being pointed at.
      top = (vh - ch) / 2;
      left = rect.left >= vw - rect.right ? m : vw - cw - m;
    }
    card.style.top = Math.min(Math.max(m, top), Math.max(m, vh - ch - m)) + 'px';
    card.style.left = Math.min(Math.max(m, left), Math.max(m, vw - cw - m)) + 'px';
  }

  function paint() {
    var step = items[idx];
    var target = null;
    try { target = document.querySelector(step.getAttribute('data-target')); }
    catch (e) { target = null; }

    heading.textContent = step.getAttribute('data-title') || '';
    body.innerHTML = '';
    [].forEach.call(step.children, function (n) {
      body.appendChild(n.cloneNode(true)); // server-escaped copy
    });
    count.textContent = (idx + 1) + ' / ' + items.length;
    backBtn.disabled = idx === 0;
    nextBtn.textContent = idx === items.length - 1 ? 'Done' : 'Next';

    clearLit();
    if (target && target.scrollIntoView) {
      // On the bottom-sheet layout the card owns the lower half of the
      // screen, so the subject goes to the top rather than the middle.
      target.scrollIntoView({block: narrow() ? 'start' : 'center', inline: 'nearest'});
    }
    // One frame later the scroll has settled, so the rect is the real one.
    requestAnimationFrame(function () {
      var rect = target ? target.getBoundingClientRect() : null;
      if (narrow() || !rect || !rect.width || !rect.height) {
        spot.className = 'tour-spot is-blank';
        spot.style.top = '-9999px';
        spot.style.left = '-9999px';
        spot.style.width = '0px';
        spot.style.height = '0px';
        if (narrow() && target) { target.classList.add('tour-lit'); lit = target; }
        placeCard(null);
        return;
      }
      var p = 8;
      spot.className = 'tour-spot';
      spot.style.top = (rect.top - p) + 'px';
      spot.style.left = (rect.left - p) + 'px';
      spot.style.width = (rect.width + p * 2) + 'px';
      spot.style.height = (rect.height + p * 2) + 'px';
      placeCard({
        top: rect.top - p, left: rect.left - p,
        bottom: rect.bottom + p, right: rect.right + p
      });
    });
  }

  function go(delta) {
    var next = idx + delta;
    if (next < 0) return;
    if (next >= items.length) { stop(); return; }
    idx = next;
    paint();
    nextBtn.focus();
  }

  function stop() {
    open = false;
    root.hidden = true;
    clearLit();
    document.removeEventListener('keydown', onKey, true);
    if (opener && opener.focus) opener.focus();
  }

  function onKey(e) {
    if (!open) return;
    if (e.key === 'Escape') { e.preventDefault(); stop(); }
    else if (e.key === 'ArrowRight') { e.preventDefault(); go(1); }
    else if (e.key === 'ArrowLeft') { e.preventDefault(); go(-1); }
    else if (e.key === 'Tab') {
      // Keep focus inside the dialog: the page behind is inert for now.
      var focusables = [].filter.call(
        card.querySelectorAll('button:not([disabled]), a[href]'),
        function (n) { return n.offsetParent !== null; }
      );
      if (!focusables.length) return;
      var first = focusables[0], last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault(); last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault(); first.focus();
      }
    }
  }

  function begin() {
    opener = document.activeElement;
    idx = 0;
    open = true;
    root.hidden = false;
    document.addEventListener('keydown', onKey, true);
    paint();
    nextBtn.focus();
  }

  // The copy describes one specific run, so make sure that run is the one on
  // screen before pointing at it. Then wait for the fetched fragment to land.
  function start() {
    var id = steps.getAttribute('data-inv');
    if (id && location.hash.slice(1) !== id) {
      location.hash = '#' + id;
    }
    var tries = 0;
    (function wait() {
      var stamp = pane && pane.querySelector('.verdict-id');
      if (!id || (stamp && stamp.textContent.trim() === id) || tries > 60) {
        begin();
        return;
      }
      tries++;
      setTimeout(wait, 50);
    })();
  }

  startBtn.addEventListener('click', start);
  nextBtn.addEventListener('click', function () { go(1); });
  backBtn.addEventListener('click', function () { go(-1); });
  closeBtn.addEventListener('click', stop);
  window.addEventListener('resize', function () { if (open) paint(); });

  // Deep link: /?tour=1 walks a visitor straight into the walkthrough.
  if (/[?&]tour=1(&|$)/.test(location.search)) {
    start();
  }
})();
"""

# --------------------------------------------------------------------------
# The case-file skin. Appended to the sheet only when hero=True, and namespaced
# under `.case*` / `body.has-hero` so `argus console` renders byte-for-byte the
# page it rendered before this existed.
#
# The band is four things and no more: the run's own timeline typing itself
# out, the elapsed time as the headline, one line saying what ARGUS is, and the
# tour prompt. Everything else on the page is the working console, spaced and
# quieted so it reads next to a SigNoz dashboard without shouting over it.
# --------------------------------------------------------------------------

_CASE_CSS = r"""
/* ---- palette: the night shift (default) ---- */
body.has-hero{
  --bg-canvas:#0B0A10; --bg-surface:#110F18; --bg-raised:#181524;
  --hairline:rgba(233,231,244,.09); --border:rgba(233,231,244,.17);
  --text-1:#E9E7F4; --text-2:#9C97AE; --text-3:#77718F;
  --accent:#8B5CF6; --accent-dim:rgba(139,92,246,.15);
  --green:#3DD68C; --amber:#F5A623; --red:#E5484D;
  --plate:#15121F; --rule:rgba(233,231,244,.16);
  --scrim:rgba(6,5,11,.78); --tex:233,231,244; --tex-a:.10;
  --lift:0 18px 48px rgba(0,0,0,.55);
  height:auto; min-height:100%;
}
/* ---- palette: the printed case file ---- */
body.has-hero[data-theme="light"]{
  --bg-canvas:#EFECE3; --bg-surface:#F7F5EE; --bg-raised:#E5E1D5;
  --hairline:rgba(28,24,38,.13); --border:rgba(28,24,38,.22);
  --text-1:#1B1726; --text-2:#544E62; --text-3:#6E687B;
  --accent:#6A38CE; --accent-dim:rgba(106,56,206,.12);
  --green:#12704A; --amber:#8A5A00; --red:#B02026;
  --plate:#F7F5EE; --rule:rgba(28,24,38,.18);
  --scrim:rgba(28,24,38,.5); --tex:28,24,38; --tex-a:.09;
  --lift:0 16px 40px rgba(28,24,38,.16);
}
@media (prefers-color-scheme:light){
  body.has-hero[data-theme="auto"]{
    --bg-canvas:#EFECE3; --bg-surface:#F7F5EE; --bg-raised:#E5E1D5;
    --hairline:rgba(28,24,38,.13); --border:rgba(28,24,38,.22);
    --text-1:#1B1726; --text-2:#544E62; --text-3:#6E687B;
    --accent:#6A38CE; --accent-dim:rgba(106,56,206,.12);
    --green:#12704A; --amber:#8A5A00; --red:#B02026;
    --plate:#F7F5EE; --rule:rgba(28,24,38,.18);
    --scrim:rgba(28,24,38,.5); --tex:28,24,38; --tex-a:.09;
    --lift:0 16px 40px rgba(28,24,38,.16);
  }
}
/* The one mark that is painted ON a semantic colour rather than in it. */
body.has-hero[data-theme="light"] .hyp-mark{color:#F7F5EE}
/* The brand mark carries the night palette's violet inside its own SVG, so on
   paper it is darkened to sit at the same weight as the rest of the ink. */
body.has-hero[data-theme="light"] .case-side .hero-mark{
  filter:saturate(1.3) brightness(.74);
}
/* The three tool accents are tuned for a dark canvas; on paper each drops to a
   printable ink of the same hue so the family row stays legible. */
body.has-hero[data-theme="light"] .fam-argus{color:#6A38CE}
body.has-hero[data-theme="light"] .fam-glasspane{color:#2F5FBF}
body.has-hero[data-theme="light"] .fam-telelens{color:#0F766E}
@media (prefers-color-scheme:light){
  body.has-hero[data-theme="auto"] .hyp-mark{color:#F7F5EE}
  body.has-hero[data-theme="auto"] .case-side .hero-mark{
    filter:saturate(1.3) brightness(.74);
  }
  body.has-hero[data-theme="auto"] .fam-argus{color:#6A38CE}
  body.has-hero[data-theme="auto"] .fam-glasspane{color:#2F5FBF}
  body.has-hero[data-theme="auto"] .fam-telelens{color:#0F766E}
}

/* ---- the band ---- */
.case{
  position:relative; overflow:hidden; background:var(--bg-canvas);
  padding:36px 44px 32px; border-bottom:1px solid var(--hairline);
}
/* Texture, derived from the subject: a terminal's dot pitch and scanline,
   faded out before it reaches the console below. */
.case::before{
  content:""; position:absolute; inset:0; pointer-events:none;
  background-image:
    repeating-linear-gradient(0deg,
      rgba(var(--tex),.03) 0 1px,transparent 1px 3px),
    radial-gradient(rgba(var(--tex),var(--tex-a)) 1px,transparent 1px);
  background-size:auto,24px 24px;
  -webkit-mask-image:linear-gradient(180deg,#000,#000 50%,transparent);
  mask-image:linear-gradient(180deg,#000,#000 50%,transparent);
}
.case-grid{
  position:relative; display:grid; gap:56px; align-items:start;
  grid-template-columns:minmax(0,1fr) minmax(170px,210px);
  max-width:1280px; margin:0 auto;
}

/* ---- the tape: the run's own timeline, in the order it was written ---- */
.case-tape{margin:0 0 22px; max-width:880px}
.case-line{
  display:grid; grid-template-columns:74px minmax(0,1fr) 48px; gap:14px;
  align-items:baseline; margin:0; padding:6px 0 6px 16px;
  border-left:2px solid var(--rule);
  font-size:12.5px; line-height:1.55;
}
.case-clock{color:var(--text-3); font-variant-numeric:tabular-nums}
.case-text{color:var(--text-2); overflow-wrap:anywhere}
.case-off{
  color:var(--text-3); text-align:right; font-size:11px;
  font-variant-numeric:tabular-nums;
}
/* Violet marks the moment a claim survived a check. Nowhere else. */
.case-confirmed{border-left-color:var(--accent)}
.case-confirmed .case-text{color:var(--text-1)}
.case-confirmed .case-off{color:var(--accent)}
.case-text.is-typing::after{
  content:""; display:inline-block; width:.55em; height:1em;
  background:var(--text-3); vertical-align:-.13em; margin-left:1px;
}

/* ---- the headline: mono at display scale, the terminal's own voice ---- */
.case-thesis{
  margin:0 0 16px; max-width:22ch;
  font-family:var(--mono); font-weight:700;
  font-size:clamp(26px,2.6vw,37px); line-height:1.1;
  letter-spacing:-.045em; color:var(--text-1);
}
.case-say{
  margin:0 0 26px; max-width:74ch;
  font-size:14px; line-height:1.6; color:var(--text-2);
}

/* ---- the tour prompt: a shell line, not a marketing button ---- */
.case-prompt{
  display:inline-flex; align-items:center; gap:9px; cursor:pointer;
  font:inherit; font-family:var(--mono); font-size:13.5px; font-weight:500;
  color:var(--text-1); background:var(--plate);
  border:1px solid var(--border); border-left:2px solid var(--accent);
  border-radius:4px; padding:12px 20px 12px 15px;
  transition:background .14s,border-color .14s;
}
.case-prompt:hover{background:var(--bg-raised); border-color:var(--accent)}
.case-prompt:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
.case-caret{color:var(--text-3)}
.case-act{display:flex; align-items:center; flex-wrap:wrap; gap:14px 26px}

/* ---- the one small line that carries every number ---- */
.case-set{
  margin:0; font-size:12px; color:var(--text-3);
  letter-spacing:.01em; font-variant-numeric:tabular-nums;
}
.case-dot{margin:0 9px}
/* "1 verified" is one fact; never let it break across two lines. */
.case-set>span,.case-verified{white-space:nowrap}
.case-verified{color:var(--accent)}

/* ---- the quiet right column ---- */
/* No rule between the columns: the gap already separates them, and a hairline
   that stops halfway down the band reads as a stray stroke. */
.case-side{
  padding:2px 0 0; display:flex; flex-direction:column;
  align-items:flex-start; gap:18px;
}
.case-brand{display:flex; align-items:center; gap:12px; width:100%}
.case-theme{margin-left:auto}
.case-side .hero-mark{width:23px; height:23px}
.case-word{font-weight:600; font-size:14px; letter-spacing:.22em; color:var(--text-1)}
.case-repo{
  font-size:12.5px; color:var(--text-1); text-decoration:none;
  border-bottom:1px solid var(--border); padding-bottom:3px;
  transition:color .14s,border-color .14s;
}
.case-repo:hover{color:var(--accent); border-bottom-color:var(--accent)}
.case-repo:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
/* Borderless: the tour prompt is the band's only boxed element, and a second
   box in the corner competed with it for the eye. */
.case-theme{
  font:inherit; font-family:var(--mono); font-size:10px; cursor:pointer;
  text-transform:uppercase; letter-spacing:.14em; color:var(--text-3);
  background:transparent; border:none; padding:4px 0;
  border-bottom:1px solid transparent; transition:color .14s,border-color .14s;
}
.case-theme:hover{color:var(--text-1); border-bottom-color:var(--border)}
.case-theme:focus-visible{outline:2px solid var(--accent); outline-offset:3px}

/* ---- the console below: same information, more air ----
   The band is the only loud thing on the page. The working tool underneath
   gets SigNoz's discipline instead: wider rows, quieter badges, one accent. */
/* The band sizes itself to its content and the console takes what is left via
   flex, rather than a hand-tuned pixel budget that drifts when the copy does.
   On a desktop-sized window the document itself must not scroll: the rail
   scrolls one way and the RCA pane the other, so opening a run can never
   scroll the band off the top of the page. */
body.has-hero{display:flex; flex-direction:column; min-height:100vh}
body.has-hero .case{flex:none}
body.has-hero .layout{flex:1 1 auto; height:auto; min-height:480px}
@media (min-width:761px) and (min-height:620px){
  body.has-hero{height:100vh; min-height:0; overflow:hidden}
  body.has-hero .layout{min-height:0}
}
body.has-hero .rail{padding:10px}
body.has-hero .row{padding:14px 14px; margin-bottom:6px; border-radius:4px}
body.has-hero .row-alert{margin-bottom:7px}
body.has-hero .row-meta{margin-top:3px}
body.has-hero .badge{
  background:transparent; border-color:transparent; padding:0;
  font-size:10px; font-weight:600; letter-spacing:.1em;
}
body.has-hero .rail-toolbar{padding:14px 14px 12px}
body.has-hero .filter-input{border-radius:4px; padding:8px 11px}
body.has-hero .chip-filter{border-radius:4px; padding:4px 9px}
body.has-hero .pane{padding:40px 44px 72px}
body.has-hero .card{
  border-radius:4px; padding:24px 26px; margin-bottom:22px;
  background:var(--bg-surface);
}
body.has-hero .card h3{margin-bottom:16px; letter-spacing:.09em}
body.has-hero .chip{border-radius:3px}
body.has-hero .verdict{margin-bottom:30px}
body.has-hero .review-banner{border-radius:4px; margin-bottom:26px}
body.has-hero .hyp{border-radius:4px; padding:14px 16px}
body.has-hero .hyp-list{gap:12px}
body.has-hero .ev{padding:12px 0}
body.has-hero .cost-footer{border-radius:4px; padding:20px 26px}
body.has-hero .empty-cmd,body.has-hero .pane-error,
body.has-hero .retry,body.has-hero .tour-card{border-radius:4px}

/* ---- family footer: same block and copy, the band's typography ---- */
body.has-hero .family{
  background:var(--bg-canvas); border-top:1px solid var(--hairline);
  padding:20px 44px 22px;
}
body.has-hero .fam{
  font-family:var(--mono); font-size:11.5px; font-weight:500; letter-spacing:.2em;
}
body.has-hero .fam-tag{margin-top:8px; font-size:11.5px; max-width:74ch}

/* ---- the tour, wearing whichever theme is on ---- */
body.has-hero .tour-spot{
  box-shadow:0 0 0 9999px var(--scrim),0 0 0 4px var(--accent-dim);
}
body.has-hero .tour-spot.is-blank{box-shadow:0 0 0 9999px var(--scrim)}
body.has-hero .tour-card{box-shadow:var(--lift)}
body.has-hero .tour-btn{border-radius:4px}
body.has-hero[data-theme="light"] .filter-input::-webkit-search-cancel-button{
  filter:none;
}

@media (max-width:1080px){
  .case-grid{grid-template-columns:minmax(0,1fr); gap:34px}
  .case-side{
    border-top:1px solid var(--hairline); padding:22px 0 0;
    flex-direction:row; align-items:center; gap:24px; flex-wrap:wrap;
  }
  .case-brand{width:auto}
}
@media (max-width:760px){
  .case{padding:24px 18px 26px}
  .case-line{
    grid-template-columns:70px minmax(0,1fr); gap:4px 14px;
    padding:5px 0 5px 13px; font-size:11.5px;
  }
  .case-tape{margin-bottom:18px}
  .case-clock{grid-row:1; grid-column:1}
  .case-off{grid-row:1; grid-column:2; text-align:right}
  .case-text{grid-row:2; grid-column:1 / -1}
  .case-thesis{max-width:none; font-size:clamp(25px,7.6vw,34px)}
  .case-say{margin-bottom:26px}
  body.has-hero .layout{height:auto; min-height:0}
  body.has-hero .pane{padding:26px 18px 56px}
  body.has-hero .family{padding:18px 18px 20px}
}
"""

_CASE_JS = r"""
(function () {
  var body = document.body;

  // The console centres its landing row on load. Where the page itself can
  // scroll — narrow screens, short windows — that also scrolls the band off
  // the top, so a first-time visitor lands mid-list with no idea what this is.
  // A deep link (#inv-…) is a deliberate request for a row, so it is left be.
  if (!location.hash) {
    window.scrollTo(0, 0);
    requestAnimationFrame(function () { window.scrollTo(0, 0); });
  }

  // ---- theme: OS by default, pinned by the band's toggle ------------------
  var toggle = document.getElementById('theme-toggle');
  var store = null;
  try { store = window.localStorage; } catch (e) { store = null; }

  function effective() {
    var t = body.getAttribute('data-theme');
    if (t === 'light' || t === 'dark') return t;
    return window.matchMedia &&
      window.matchMedia('(prefers-color-scheme: light)').matches
      ? 'light' : 'dark';
  }

  function label() {
    if (!toggle) return;
    var next = effective() === 'light' ? 'night' : 'paper';
    toggle.textContent = next;
    toggle.setAttribute('aria-label', 'Switch to the ' + next + ' theme');
  }

  var saved = store && store.getItem('argus-theme');
  if (saved === 'light' || saved === 'dark') body.setAttribute('data-theme', saved);
  label();

  if (toggle) {
    toggle.addEventListener('click', function () {
      var next = effective() === 'light' ? 'dark' : 'light';
      body.setAttribute('data-theme', next);
      if (store) { try { store.setItem('argus-theme', next); } catch (e) {} }
      label();
    });
  }
  if (window.matchMedia) {
    var mq = window.matchMedia('(prefers-color-scheme: light)');
    var onOS = function () { if (body.getAttribute('data-theme') === 'auto') label(); };
    if (mq.addEventListener) mq.addEventListener('change', onOS);
  }

  // ---- the tape types itself out, once, on load ---------------------------
  // The text is already in the DOM (server-escaped), so a reader with no
  // JavaScript — or with "reduce motion" on — gets the finished timeline.
  var cells = [].slice.call(
    document.querySelectorAll('#case-tape .case-text[data-type]')
  );
  if (!cells.length) return;
  if (window.matchMedia &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;

  var plan = cells.map(function (el) {
    // Reserve the finished height first: a line that grows as it types would
    // shove the headline down the page three times.
    el.style.minHeight = el.getBoundingClientRect().height + 'px';
    var text = el.textContent;
    el.textContent = '';
    return {el: el, text: text};
  });

  var i = 0;
  function typeLine() {
    if (i >= plan.length) return;
    var line = plan[i], n = 0;
    line.el.classList.add('is-typing');
    (function tick() {
      n += 2;
      line.el.textContent = line.text.slice(0, n);
      if (n < line.text.length) { setTimeout(tick, 14); return; }
      line.el.textContent = line.text;
      line.el.classList.remove('is-typing');
      i++;
      setTimeout(typeLine, 220);
    })();
  }
  typeLine();
})();
"""
