"""Read-only data layer for the ARGUS Investigations Console.

Everything here is derived from local files ARGUS already writes — never a
live SigNoz or LLM call. Each investigation is reconstructed from its
``postmortems/<id>.report.json`` (the structured RCA contract) plus its
sibling ``<id>.md`` (which carries the metadata header and the token/$ cost
line that the JSON omits). The incident-memory SQLite is used as a fallback
for service/alert/date when a markdown header is missing.

IMPORTANT: every string in the returned structures is telemetry-derived and
therefore UNTRUSTED. This module does no escaping — it is the render layer's
job to escape on the way out (see ``render.py``). Keeping raw text here means
the CLI/tests can assert on the real content.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# ---- markdown-header regexes (the .md format ARGUS writes is stable) --------
_RE_SERVICE = re.compile(r"^- \*\*Service:\*\* `([^`]*)`", re.MULTILINE)
_RE_ALERT = re.compile(r"^- \*\*Alert:\*\* `([^`]*)`", re.MULTILINE)
_RE_GENERATED = re.compile(
    r"^- \*\*Generated:\*\* (\d{4}-\d{2}-\d{2} \d{2}:\d{2}(?::\d{2})? UTC)",
    re.MULTILINE,
)
_RE_COST_MODEL = re.compile(r"^- LLM: (.+)$", re.MULTILINE)
_RE_COST_TOKENS = re.compile(
    r"tokens: ([\d,]+) in / ([\d,]+) out, est\. \$([0-9.]+)"
)
_RE_COST_CALLS = re.compile(r"LLM calls: (\d+)")

# ---- evidence / link extraction --------------------------------------------
# Slack mrkdwn link:  <https://…|label>
_RE_SLACK_LINK = re.compile(r"<(https?://[^|>]+)\|[^>]*>")
_RE_BARE_URL = re.compile(r"(https?://\S+)")
# root-cause verification tail:  "(verified: found 'pg_sleep' in 20 rows)"
_RE_VERIFIED_TAIL = re.compile(r"\(verified:\s*(.+?)\)\s*$")


@dataclass
class Hypothesis:
    verdict: str  # "CONFIRMED" | "REFUTED" | "ERROR"
    text: str
    detail: str = ""


@dataclass
class Evidence:
    text: str
    url: str = ""


@dataclass
class Cost:
    model: str = ""
    llm_calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    usd: float = 0.0
    query_stats: str = ""  # "18 SigNoz queries · 478,556 rows / 47.0 MB scanned"


@dataclass
class Investigation:
    id: str
    title: str
    service: str
    alert: str
    date_display: str
    date_sort: str
    confidence: float
    degraded: bool
    needs_review: bool
    root_cause: str
    impact: str
    timeline: list[str] = field(default_factory=list)
    hypotheses: list[Hypothesis] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    similar: list[str] = field(default_factory=list)
    extra_links: list[Evidence] = field(default_factory=list)  # dashboard / draft rule
    cost: Cost = field(default_factory=Cost)

    @property
    def status(self) -> str:
        """Confidence badge, per the design system's sacred severity colors."""
        if self.degraded:
            return "DEGRADED"
        if self.confidence >= 0.75:
            return "VERIFIED"
        return "NEEDS REVIEW"


# ---------------------------------------------------------------------------


def _split_link(bullet: str) -> Evidence:
    """Pull a URL out of an evidence bullet, returning clean text + url."""
    m = _RE_SLACK_LINK.search(bullet)
    if m:
        url = m.group(1)
        text = bullet[: m.start()].rstrip()
        text = text.rstrip("(").rstrip()  # drop the " (" that wrapped the link
        return Evidence(text=text or bullet, url=url)
    m2 = _RE_BARE_URL.search(bullet)
    if m2:
        url = m2.group(1)
        text = bullet.replace(url, "").rstrip(" :—-").rstrip()
        return Evidence(text=text or bullet, url=url)
    return Evidence(text=bullet)


def _parse_hypotheses(root_cause: str, refuted: list[str], degraded: bool) -> list[Hypothesis]:
    """Reconstruct confirmed/refuted/errored hypotheses from the JSON contract.

    The winning hypothesis lives in ``root_cause`` (with a ``(verified: …)``
    tail); the losers live in ``refuted`` (each tagged with why it failed —
    "verification failed to run" means the check errored, anything else means
    the telemetry actively contradicted it).
    """
    out: list[Hypothesis] = []
    if root_cause and not degraded:
        detail = ""
        m = _RE_VERIFIED_TAIL.search(root_cause)
        text = root_cause
        if m:
            detail = m.group(1).strip()
            text = root_cause[: m.start()].rstrip()
        out.append(Hypothesis(verdict="CONFIRMED", text=text, detail=detail))
    for r in refuted:
        # Detail begins at the " — verification…" seam ARGUS writes.
        seam = r.find(" — verification")
        if seam == -1:
            seam = r.find("— verification")
        if seam != -1:
            text = r[:seam].rstrip(" —").rstrip()
            detail = r[seam:].lstrip(" —").rstrip()
        else:
            text, detail = r, ""
        verdict = "ERROR" if "verification failed to run" in r or "failed to run" in detail else "REFUTED"
        out.append(Hypothesis(verdict=verdict, text=text, detail=detail))
    return out


def _parse_md_meta(md_text: str) -> dict:
    meta: dict = {}
    if m := _RE_SERVICE.search(md_text):
        meta["service"] = m.group(1)
    if m := _RE_ALERT.search(md_text):
        meta["alert"] = m.group(1)
    if m := _RE_GENERATED.search(md_text):
        meta["generated"] = m.group(1)
    cost = Cost()
    if m := _RE_COST_MODEL.search(md_text):
        cost.model = m.group(1).strip()
    if m := _RE_COST_CALLS.search(md_text):
        cost.llm_calls = int(m.group(1))
    if m := _RE_COST_TOKENS.search(md_text):
        cost.tokens_in = int(m.group(1).replace(",", ""))
        cost.tokens_out = int(m.group(2).replace(",", ""))
        cost.usd = float(m.group(3))
    meta["cost"] = cost
    return meta


def load_investigation(report_path: Path, memory_lookup: Optional[dict] = None) -> Investigation:
    """Build one Investigation from a ``<id>.report.json`` file."""
    inv_id = report_path.name.removesuffix(".report.json")
    payload = json.loads(report_path.read_text())

    md_path = report_path.with_name(f"{inv_id}.md")
    md_meta: dict = {}
    if md_path.is_file():
        md_meta = _parse_md_meta(md_path.read_text())

    mem = (memory_lookup or {}).get(inv_id, {})

    title = payload.get("title", inv_id)
    # Prefer the markdown header; fall back to memory DB, then to the title.
    alert_from_title, _, service_from_title = title.partition(" — ")
    service = md_meta.get("service") or mem.get("service") or service_from_title or "unknown"
    alert = md_meta.get("alert") or mem.get("alert_name") or alert_from_title or title
    generated = md_meta.get("generated") or ""
    date_sort = mem.get("occurred_at", "") or _generated_to_iso(generated)
    date_display = generated or (mem.get("occurred_at", "")[:16].replace("T", " ") + " UTC" if mem.get("occurred_at") else "")

    cost: Cost = md_meta.get("cost", Cost())
    if not cost.model and isinstance(mem.get("cost"), dict):
        # No .md header on this checkout — fall back to the recorded sidecar so
        # the token/$ footprint doesn't silently read as zero.
        mc = mem["cost"]
        cost = Cost(
            model=str(mc.get("model", "")),
            tokens_in=int(mc.get("tokens_in", 0) or 0),
            tokens_out=int(mc.get("tokens_out", 0) or 0),
            usd=float(mc.get("usd", 0.0) or 0.0),
        )
    cost.query_stats = payload.get("query_stats", "")

    # Split evidence_bullets into evidence / similar-incidents / extra links.
    evidence: list[Evidence] = []
    similar: list[str] = []
    extra_links: list[Evidence] = []
    for bullet in payload.get("evidence_bullets", []):
        low = bullet.lower()
        if low.startswith("similar to incident"):
            similar.append(bullet)
        elif "dashboard auto-created" in low or "draft follow-up alert rule" in low:
            extra_links.append(_split_link(bullet))
        else:
            evidence.append(_split_link(bullet))

    return Investigation(
        id=inv_id,
        title=title,
        service=service,
        alert=alert,
        date_display=date_display,
        date_sort=date_sort,
        confidence=float(payload.get("confidence", 0.0)),
        degraded=bool(payload.get("degraded", False)),
        needs_review=bool(payload.get("needs_review", False)),
        root_cause=payload.get("root_cause", ""),
        impact=payload.get("impact", ""),
        timeline=list(payload.get("timeline", [])),
        hypotheses=_parse_hypotheses(
            payload.get("root_cause", ""),
            list(payload.get("refuted", [])),
            bool(payload.get("degraded", False)),
        ),
        evidence=evidence,
        similar=similar,
        extra_links=extra_links,
        cost=cost,
    )


def _generated_to_iso(generated: str) -> str:
    """'2026-07-17 21:35 UTC' -> a sortable ISO-ish string."""
    m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}(?::\d{2})?)", generated or "")
    return f"{m.group(1)}T{m.group(2)}" if m else ""


def _memory_lookup(memory_db: Optional[Path]) -> dict:
    """Best-effort {incident_id: {service, alert_name, occurred_at}} from SQLite."""
    if not memory_db or not Path(memory_db).is_file():
        return {}
    import sqlite3

    try:
        conn = sqlite3.connect(str(memory_db))
        rows = conn.execute(
            "SELECT incident_id, occurred_at, alert_name, service FROM incidents"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    return {
        r[0]: {"occurred_at": r[1], "alert_name": r[2], "service": r[3]}
        for r in rows
    }


def _sidecar_lookup(postmortem_dir: Path) -> dict:
    """Recorded metadata for the committed corpus, in the memory-lookup shape.

    A ``.md`` postmortem carries the service/alert/timestamp header, but ``.md``
    files are per-run output and gitignored — and so is the incident-memory DB.
    Without either, a clean clone can only show "unknown / undated" for reports
    whose metadata it genuinely has on record elsewhere. ``metadata.json`` is
    that record, committed alongside the corpus. It is a *fallback*: a real
    ``.md`` header or a live memory DB always wins.
    """
    path = Path(postmortem_dir) / "metadata.json"
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    incidents = payload.get("incidents")
    return incidents if isinstance(incidents, dict) else {}


def load_investigations(
    postmortem_dir: Path, memory_db: Optional[Path] = None
) -> list[Investigation]:
    """Load every investigation, newest first.

    Ordering is deliberate. A report whose sibling ``.md`` was pruned (they are
    per-run output and gitignored) and that the memory DB doesn't know about has
    no timestamp at all. Sorting those by their id would be sorting by random
    hex — so undated investigations are grouped *after* every dated one and
    ordered stably by id, instead of being interleaved arbitrarily.
    """
    postmortem_dir = Path(postmortem_dir)
    if not postmortem_dir.is_dir():
        return []
    mem = dict(_sidecar_lookup(postmortem_dir))
    mem.update(_memory_lookup(memory_db))  # a live memory DB wins over the sidecar
    invs = [
        load_investigation(p, mem)
        for p in sorted(postmortem_dir.glob("*.report.json"))
    ]
    # (has-a-date, date) descending puts dated newest-first, undated last;
    # the pre-sorted-by-id input keeps the undated tail deterministic.
    invs.sort(key=lambda i: (bool(i.date_sort), i.date_sort), reverse=True)
    return invs


def default_selection(invs: list[Investigation]) -> Optional[Investigation]:
    """Which investigation the console should open on.

    The rail is ordered honestly (newest first), but "newest" and "most useful
    to look at first" are different questions. Opening on whatever ran last
    means a visitor's first view is often a low-confidence draft, when the
    corpus contains a run that actually cleared the 75% verification threshold.

    So: open on the highest-confidence VERIFIED investigation if there is one,
    otherwise on the newest. Ties go to the newer run, since ``invs`` arrives
    newest-first and ``max`` keeps the first of equal keys. Nothing is hidden —
    the rail still lists every investigation, drafts and degraded runs included.
    """
    if not invs:
        return None
    verified = [i for i in invs if i.status == "VERIFIED"]
    if verified:
        return max(verified, key=lambda i: i.confidence)
    return invs[0]


@dataclass
class Stats:
    total: int
    verified: int
    total_usd: float

    @property
    def verified_pct(self) -> int:
        return round(100 * self.verified / self.total) if self.total else 0


def compute_stats(invs: list[Investigation]) -> Stats:
    return Stats(
        total=len(invs),
        verified=sum(1 for i in invs if i.status == "VERIFIED"),
        total_usd=round(sum(i.cost.usd for i in invs), 4),
    )
