"""Shared plumbing for every Faultline service: fault-flag registry with an
admin router (used by faultctl), plus helpers."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, FastAPI, HTTPException

logger = logging.getLogger("faultline")

# Fault flags are process-local; faultctl flips them over HTTP per service.
FAULTS: dict[str, bool] = {}


def fault_active(name: str) -> bool:
    return FAULTS.get(name, False)


def make_app(service: str, known_faults: list[str]) -> FastAPI:
    app = FastAPI(title=f"faultline-{service}")
    for f in known_faults:
        FAULTS.setdefault(f, False)

    admin = APIRouter(prefix="/_fault")

    @admin.get("")
    def list_faults() -> dict[str, bool]:
        return dict(FAULTS)

    @admin.post("/{name}/{action}")
    def set_fault(name: str, action: str) -> dict[str, bool]:
        if name not in FAULTS:
            raise HTTPException(404, f"unknown fault '{name}' (known: {list(FAULTS)})")
        if action not in ("on", "off"):
            raise HTTPException(400, "action must be 'on' or 'off'")
        FAULTS[name] = action == "on"
        logger.warning("fault '%s' switched %s on %s", name, action, service)
        return dict(FAULTS)

    app.include_router(admin)

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": service,
                "version": os.getenv("SERVICE_VERSION", "1.0.0")}

    return app
