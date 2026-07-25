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


def _hyp_card(h) -> str:
    marks = {"CONFIRMED": ("✓", "hyp-confirmed"), "REFUTED": ("✗", "hyp-refuted"),
             "ERROR": ("!", "hyp-error")}
    mark, cls = marks.get(h.verdict, ("·", "hyp-error"))
    detail = (
        f'<div class="hyp-detail">{esc(h.detail)}</div>' if h.detail else ""
    )
    return (
        f'<div class="hyp {cls}">'
        f'<div class="hyp-head"><span class="hyp-mark">{esc(mark)}</span>'
        f'<span class="hyp-verdict">{esc(h.verdict)}</span></div>'
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

_HERO_PROP = (
    "An autonomous AI SRE for self-hosted SigNoz. It investigates the alert on "
    "its own, verifies every hypothesis against your telemetry, and refuses to "
    "report what it cannot prove."
)


def _hero_chips(invs: list[Investigation], stats: Stats) -> list[tuple[str, str]]:
    """The landing stat chips, derived from the corpus so they cannot drift."""
    verified = [i for i in invs if i.status == "VERIFIED"]
    best = max((i.confidence for i in verified), default=0.0)
    verified_label = (
        f"verified RCA at {round(best * 100)}%"
        if len(verified) == 1
        else "verified RCAs"
    )
    return [
        (str(stats.total), "recorded investigations"),
        (str(len(verified)), verified_label),
        (f"${stats.total_usd:.2f}", "total LLM spend"),
        ("0", "runtime dependencies"),
    ]


def render_hero(invs: list[Investigation], stats: Stats) -> str:
    """A compact landing band for the published static export.

    The served console is a working tool — an operator who typed ``argus
    console`` does not need to be sold the product. The published bundle is the
    opposite: it is the first thing a stranger sees, so it gets one short band
    that says what ARGUS is, what the corpus below proves, and where the source
    lives. It replaces the topbar rather than stacking on top of it, so the
    investigations stay above the fold.
    """
    chips = "".join(
        f'<span class="hero-chip"><b class="mono">{esc(value)}</b>'
        f'<span class="hero-chip-label">{esc(label)}</span></span>'
        for value, label in _hero_chips(invs, stats)
    )
    return f"""<header class="hero">
  <div class="hero-row">
    <div class="hero-brand">{_HERO_MARK}<span class="hero-word">ARGUS</span></div>
    <p class="hero-prop">{esc(_HERO_PROP)}</p>
    <div class="hero-actions">
      <a class="hero-btn hero-btn-primary" href="{safe_url(REPO_URL)}"
         target="_blank" rel="noopener noreferrer">GitHub &rarr;</a>
      <button class="hero-btn hero-btn-ghost" id="hero-scroll"
              type="button">See the evidence &darr;</button>
    </div>
  </div>
  <div class="hero-chips">{chips}</div>
</header>"""


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
    return _PAGE_TEMPLATE.format(
        css=_CSS,
        accent=ACCENT,
        body_class=" class=\"has-hero\"" if hero else "",
        header=render_hero(invs, stats) if hero else _topbar(stats),
        filters=render_filters(invs) if invs else "",
        list_html=list_html,
        empty_detail=empty_detail,
        js=_JS,
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
</main>
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
  height:var(--hero-h); flex:none; box-sizing:border-box;
  padding:14px 24px 12px; border-bottom:1px solid var(--hairline);
  background:
    radial-gradient(700px 130px at 8% -40%,rgba(139,92,246,.13),transparent 70%),
    var(--bg-surface);
}
.hero-row{display:flex; align-items:center; gap:24px}
.hero-brand{display:flex; align-items:center; gap:9px; flex:none}
.hero-mark{width:26px; height:26px; display:block}
.hero-word{font-weight:600; font-size:17px; letter-spacing:.16em}
.hero-prop{
  margin:0; flex:1 1 auto; min-width:0; max-width:74ch;
  font-size:12.5px; line-height:1.45; color:var(--text-2);
}
.hero-actions{display:flex; align-items:center; gap:8px; flex:none}
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
.hero-chips{display:flex; flex-wrap:wrap; align-items:center; gap:7px; margin-top:11px}
.hero-chip{
  display:inline-flex; align-items:baseline; gap:6px;
  border:1px solid var(--hairline); border-radius:999px; padding:2.5px 10px;
  font-size:11.5px; color:var(--text-3); background:var(--bg-canvas);
}
.hero-chip b{font-size:12.5px; font-weight:600; color:var(--text-1)}
.hero-chip-label{white-space:nowrap}

/* ---- layout ---- */
.layout{display:grid; grid-template-columns:320px 1fr; height:calc(100% - 56px)}
.has-hero .layout{height:calc(100% - 112px)}
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
.hyp-error{border-left-color:var(--amber)}
.hyp-error .hyp-mark{background:var(--amber)} .hyp-error .hyp-verdict{color:var(--amber)}

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
  .hero{height:auto; padding:16px}
  .hero-row{flex-wrap:wrap; gap:12px}
  .hero-prop{flex:1 1 100%; order:3; max-width:none}
  .hero-actions{margin-left:auto}
}
"""
