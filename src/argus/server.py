"""FastAPI webhook server: POST /webhook/signoz -> deduped background
investigation; GET /healthz; GET /investigations (status listing).

Dedup (FR-2/NFR-3): fingerprint = alert identity + window rounded to 5
minutes. Re-delivery of the same alert returns the existing investigation id
and never spawns a duplicate. Concurrency: one in-flight investigation per
service.
"""

from __future__ import annotations

import hmac
import json
import logging
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request

from .config import Settings
from .models import TimeWindow, dedup_fingerprint
from .nodes.triage import LOOKBACK_MINUTES, TriageError, parse_webhook

logger = logging.getLogger("argus.server")

_STATE_SCHEMA = """
CREATE TABLE IF NOT EXISTS dedup (
    fingerprint      TEXT PRIMARY KEY,
    investigation_id TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS results (
    investigation_id TEXT PRIMARY KEY,
    payload          TEXT NOT NULL
);
"""


class DedupStore:
    """Idempotency + per-service concurrency guard.

    With a `db_path`, fingerprints and results are persisted to SQLite so a
    restart cannot re-run an already-delivered alert or forget past results.
    In-flight ("running") entries found at startup are marked "interrupted" —
    the process that owned them is gone. Without a path, purely in-memory
    (tests, ephemeral runs).
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        self._lock = threading.Lock()
        self._by_fingerprint: dict[str, str] = {}  # fingerprint -> investigation_id
        self._active_services: set[str] = set()
        self.results: dict[str, dict[str, Any]] = {}  # investigation_id -> status/result
        self._conn: Optional[sqlite3.Connection] = None
        if db_path:
            path = Path(db_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.executescript(_STATE_SCHEMA)
            for fp, inv in self._conn.execute("SELECT fingerprint, investigation_id FROM dedup"):
                self._by_fingerprint[fp] = inv
            for inv, payload in self._conn.execute(
                "SELECT investigation_id, payload FROM results"
            ):
                result = json.loads(payload)
                if result.get("status") == "running":
                    result["status"] = "interrupted"
                    self._persist_result(inv, result)
                self.results[inv] = result
            self._conn.commit()

    def _persist_result(self, investigation_id: str, result: dict[str, Any]) -> None:
        if self._conn is not None:
            self._conn.execute(
                "INSERT OR REPLACE INTO results VALUES (?, ?)",
                (investigation_id, json.dumps(result)),
            )

    def claim(self, fingerprint: str, service: str, investigation_id: str) -> Optional[str]:
        """Returns existing investigation id if duplicate/busy, else None (claimed)."""
        with self._lock:
            if fingerprint in self._by_fingerprint:
                return self._by_fingerprint[fingerprint]
            if service in self._active_services:
                # One investigation per service at a time; treat as duplicate of the active one.
                for fp, inv in self._by_fingerprint.items():
                    if self.results.get(inv, {}).get("service") == service and \
                       self.results.get(inv, {}).get("status") == "running":
                        return inv
            self._by_fingerprint[fingerprint] = investigation_id
            self._active_services.add(service)
            self.results[investigation_id] = {"status": "running", "service": service}
            if self._conn is not None:
                self._conn.execute(
                    "INSERT OR REPLACE INTO dedup VALUES (?, ?)",
                    (fingerprint, investigation_id),
                )
                self._persist_result(
                    investigation_id, self.results[investigation_id]
                )
                self._conn.commit()
            return None

    def finish(self, investigation_id: str, service: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._active_services.discard(service)
            self.results[investigation_id] = {**result, "service": service}
            if self._conn is not None:
                self._persist_result(investigation_id, self.results[investigation_id])
                self._conn.commit()


def _webhook_authorized(request: Request, secret: str) -> bool:
    """Constant-time check of the shared secret, accepted either as the
    `X-Argus-Webhook-Secret` header or as `Authorization: Bearer <secret>`
    (SigNoz/Alertmanager webhook channels can set custom headers)."""
    supplied = request.headers.get("x-argus-webhook-secret", "")
    if not supplied:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            supplied = auth[7:]
    # bytes comparison: compare_digest raises TypeError on non-ASCII str,
    # and a hostile header must yield 401, not a 500
    return bool(supplied) and hmac.compare_digest(
        supplied.encode("utf-8", "surrogateescape"), secret.encode()
    )


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="ARGUS", version="0.1.0")
    dedup = DedupStore(settings.state_db if settings.state_enabled() else None)
    app.state.dedup = dedup
    if not settings.webhook_secret:
        logger.warning(
            "ARGUS_WEBHOOK_SECRET is not set — /webhook/signoz will accept "
            "unauthenticated requests. Anyone who can reach port %s can trigger "
            "investigations (and LLM spend). Set a secret and configure the "
            "SigNoz webhook channel to send it.",
            settings.listen_port,
        )

    def _make_deps():
        from .live import make_live_deps

        return make_live_deps(settings)

    def _investigate(alert, investigation_id: str, service: str) -> None:
        from .investigation import run_investigation
        from .slack import SlackPoster

        try:
            state = run_investigation(
                alert, _make_deps(), settings.max_verify_iterations,
                investigation_id=investigation_id,
            )
            report = state.report
            if report:
                SlackPoster(settings.slack_bot_token, settings.slack_channel).post(
                    report.slack_blocks, fallback_text=f"ARGUS RCA: {report.title}"
                )
                # Persist the RCA artifacts (postmortem markdown + full report JSON).
                from pathlib import Path

                out = Path("postmortems")
                out.mkdir(parents=True, exist_ok=True)
                (out / f"{investigation_id}.md").write_text(report.postmortem_md)
                (out / f"{investigation_id}.report.json").write_text(
                    report.model_dump_json(indent=2, exclude={"postmortem_md"})
                )
            dedup.finish(investigation_id, service, {
                "status": "done",
                "degraded": bool(report and report.degraded),
                "root_cause": report.root_cause if report else None,
                "cost_usd": state.usage.cost_usd,
            })
        except Exception as exc:  # noqa: BLE001
            logger.exception("investigation %s failed", investigation_id)
            dedup.finish(investigation_id, service, {"status": "error", "error": str(exc)})

    @app.post("/webhook/signoz", status_code=202)
    def webhook(
        payload: dict[str, Any], background: BackgroundTasks, request: Request
    ) -> dict[str, Any]:
        if settings.webhook_secret and not _webhook_authorized(
            request, settings.webhook_secret
        ):
            raise HTTPException(status_code=401, detail="invalid or missing webhook secret")
        try:
            alert = parse_webhook(payload)
        except TriageError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        if alert.status == "resolved":
            # send_resolved notifications are acknowledged, never investigated.
            return {"investigation_id": None, "skipped": "alert already resolved"}

        now = datetime.now(timezone.utc)
        anchor = alert.starts_at or now
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        window = TimeWindow(start=anchor - timedelta(minutes=LOOKBACK_MINUTES), end=now)
        fingerprint = dedup_fingerprint(alert, window)
        service = alert.service or "unknown"

        import uuid

        investigation_id = f"inv-{uuid.uuid4().hex[:10]}"
        existing = dedup.claim(fingerprint, service, investigation_id)
        if existing:
            return {"investigation_id": existing, "deduplicated": True}

        background.add_task(_investigate, alert, investigation_id, service)
        return {"investigation_id": investigation_id, "deduplicated": False}

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/investigations")
    def investigations() -> dict[str, Any]:
        return {"investigations": dedup.results}

    return app
