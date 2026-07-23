"""FastAPI webhook server: POST /webhook/signoz -> deduped background
investigation; GET /healthz; GET /investigations (status listing).

Dedup (FR-2/NFR-3): fingerprint = alert identity + window rounded to 5
minutes. Re-delivery of the same alert returns the existing investigation id
and never spawns a duplicate. Concurrency: one in-flight investigation per
service.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import BackgroundTasks, FastAPI, HTTPException

from .config import Settings
from .models import TimeWindow, dedup_fingerprint
from .nodes.triage import LOOKBACK_MINUTES, TriageError, parse_webhook

logger = logging.getLogger("argus.server")


class DedupStore:
    """In-memory idempotency + per-service concurrency guard."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_fingerprint: dict[str, str] = {}  # fingerprint -> investigation_id
        self._active_services: set[str] = set()
        self.results: dict[str, dict[str, Any]] = {}  # investigation_id -> status/result

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
            return None

    def finish(self, investigation_id: str, service: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._active_services.discard(service)
            self.results[investigation_id] = {**result, "service": service}


def create_app(settings: Settings) -> FastAPI:
    app = FastAPI(title="ARGUS", version="0.1.0")
    dedup = DedupStore()
    app.state.dedup = dedup

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
    def webhook(payload: dict[str, Any], background: BackgroundTasks) -> dict[str, Any]:
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
