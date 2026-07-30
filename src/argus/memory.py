"""Incident memory (FR-14): ARGUS remembers past
investigations and recalls the most similar ones into new ones.

Storage is a local SQLite file; similarity is cosine over a *local* hashed
TF embedding (feature hashing with signed buckets + sublinear term frequency
+ L2 norm — the classic "hashing trick"). Zero network, zero paid APIs, no
model downloads: the memory works offline and in CI exactly like everywhere
else. Quality grows with the corpus (honest limitation, documented).

The embedded "signature" of an incident is the text that identifies its
failure class: alert name, service, symptom summaries, root cause.
"""

from __future__ import annotations

import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

EMBED_DIM = 512

_TOKEN_RE = re.compile(r"[a-z0-9_.]{2,}")
# words that carry no incident-signature signal
_STOPWORDS = frozenset(
    "the a an is are was were be been being to of in on for and or with by at "
    "from as it its this that these those before after vs than not no".split()
)


def tokenize(text: str) -> list[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOPWORDS]


def _bucket(token: str) -> tuple[int, float]:
    """Deterministic (index, sign) for a token — the feature-hashing trick.
    Python's hash() is salted per-process, so use a stable FNV-1a."""
    h = 2166136261
    for ch in token.encode():
        h = ((h ^ ch) * 16777619) & 0xFFFFFFFF
    return h % EMBED_DIM, 1.0 if (h >> 31) & 1 else -1.0


def embed(text: str) -> list[float]:
    """Hashed sublinear-TF vector, L2-normalized. Deterministic, local."""
    vec = [0.0] * EMBED_DIM
    counts: dict[str, int] = {}
    for tok in tokenize(text):
        counts[tok] = counts.get(tok, 0) + 1
    for tok, n in counts.items():
        idx, sign = _bucket(tok)
        vec[idx] += sign * (1.0 + math.log(n))
    norm = math.sqrt(sum(v * v for v in vec))
    return [v / norm for v in vec] if norm else vec


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))  # inputs are unit vectors


@dataclass
class IncidentRecord:
    incident_id: str
    occurred_at: str  # ISO-8601 UTC
    alert_name: str
    service: str
    symptoms: str  # condensed evidence summaries
    root_cause: str
    confidence: float
    degraded: bool

    def signature(self) -> str:
        return " ".join(
            (self.alert_name, self.service, self.symptoms, self.root_cause)
        )

    def occurred_date(self) -> str:
        """Human date for citations, e.g. 'Jul 16'."""
        try:
            dt = datetime.fromisoformat(self.occurred_at.replace("Z", "+00:00"))
            return dt.strftime("%b %d").replace(" 0", " ")
        except ValueError:
            return self.occurred_at[:10]


_SCHEMA = """
CREATE TABLE IF NOT EXISTS incidents (
    incident_id TEXT PRIMARY KEY,
    occurred_at TEXT NOT NULL,
    alert_name  TEXT NOT NULL,
    service     TEXT NOT NULL,
    symptoms    TEXT NOT NULL,
    root_cause  TEXT NOT NULL,
    confidence  REAL NOT NULL,
    degraded    INTEGER NOT NULL,
    vector      TEXT NOT NULL
)
"""


class IncidentMemory:
    """SQLite-backed store with embedding recall. Corpus sizes here are
    hundreds of incidents, so recall scans all vectors (exact, no ANN)."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        # WAL survives concurrent readers (console) alongside the writer and
        # is far more robust than the default journal under a threaded server.
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute(_SCHEMA)
        self._conn.commit()

    def store(self, record: IncidentRecord) -> None:
        vec = embed(record.signature())
        self._conn.execute(
            "INSERT OR REPLACE INTO incidents VALUES (?,?,?,?,?,?,?,?,?)",
            (
                record.incident_id, record.occurred_at, record.alert_name,
                record.service, record.symptoms, record.root_cause,
                record.confidence, int(record.degraded), json.dumps(vec),
            ),
        )
        self._conn.commit()

    def recall(
        self,
        text: str,
        top_k: int = 3,
        exclude_id: Optional[str] = None,
        min_similarity: float = 0.0,
    ) -> list[tuple[float, IncidentRecord]]:
        """Top-k most similar past incidents to `text`, best first."""
        query_vec = embed(text)
        scored: list[tuple[float, IncidentRecord]] = []
        for row in self._conn.execute(
            "SELECT incident_id, occurred_at, alert_name, service, symptoms,"
            " root_cause, confidence, degraded, vector FROM incidents"
        ):
            if exclude_id and row[0] == exclude_id:
                continue
            sim = cosine(query_vec, json.loads(row[8]))
            if sim < min_similarity:
                continue
            scored.append(
                (
                    sim,
                    IncidentRecord(
                        incident_id=row[0], occurred_at=row[1], alert_name=row[2],
                        service=row[3], symptoms=row[4], root_cause=row[5],
                        confidence=row[6], degraded=bool(row[7]),
                    ),
                )
            )
        scored.sort(key=lambda t: t[0], reverse=True)
        return scored[:top_k]

    def count(self) -> int:
        return int(self._conn.execute("SELECT COUNT(*) FROM incidents").fetchone()[0])

    def all(self) -> list[IncidentRecord]:
        return [
            IncidentRecord(
                incident_id=r[0], occurred_at=r[1], alert_name=r[2], service=r[3],
                symptoms=r[4], root_cause=r[5], confidence=r[6], degraded=bool(r[7]),
            )
            for r in self._conn.execute(
                "SELECT incident_id, occurred_at, alert_name, service, symptoms,"
                " root_cause, confidence, degraded FROM incidents ORDER BY occurred_at"
            )
        ]

    def close(self) -> None:
        self._conn.close()


def record_from_state(state) -> IncidentRecord:
    """Condense a finished InvestigationState into a memory record."""
    symptoms = "; ".join(
        e.summary for e in state.available_evidence() if e.kind.value != "memory"
    )[:2000]
    report = state.report
    return IncidentRecord(
        incident_id=state.investigation_id,
        occurred_at=state.started_at.astimezone(timezone.utc).isoformat(),
        alert_name=state.alert.name,
        service=state.service,
        symptoms=symptoms,
        root_cause=(report.root_cause if report else "")[:2000],
        confidence=report.confidence if report else 0.0,
        degraded=bool(report and report.degraded),
    )
