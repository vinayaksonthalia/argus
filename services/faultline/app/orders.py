"""Orders service: creates an order, records it in Postgres, charges via payments.

Faults:
- `memory-pressure`: every request appends ~1 MB to a process-lifetime list —
  RSS climbs steadily (the "leak" incident).
- `bad-deploy`: emits a deployment change-event log (event.name=deployment,
  service.version bump) and makes order handling slower+flaky, so the root
  cause is the change correlation, not a single slow span.
"""

from __future__ import annotations

import logging
import os
import random
import time
import uuid

import httpx
import psycopg
from fastapi import HTTPException
from pydantic import BaseModel

from .common import FAULTS, fault_active, make_app

logger = logging.getLogger("faultline.orders")

DSN = os.getenv(
    "DATABASE_URL", "postgresql://faultline:faultline@localhost:5432/faultline"
)
PAYMENTS_URL = os.getenv("PAYMENTS_URL", "http://localhost:8092")

app = make_app("orders", ["memory-pressure", "bad-deploy"])

_LEAK: list[bytes] = []  # deliberate: grows under memory-pressure
_deploy_emitted = False


class NewOrder(BaseModel):
    product_id: int
    quantity: int = 1


def _maybe_emit_deploy_event() -> None:
    """First request after bad-deploy is switched on emits the change event."""
    global _deploy_emitted
    if fault_active("bad-deploy") and not _deploy_emitted:
        _deploy_emitted = True
        logger.warning(
            "deployment completed",
            extra={
                "event.name": "deployment",
                "service.version": "1.1.0-rc1",
                "vcs.commit.sha": "f4u17d3p10y",
                "deployer": "ci-bot",
            },
        )
    if not fault_active("bad-deploy"):
        _deploy_emitted = False


@app.post("/orders")
def create_order(body: NewOrder) -> dict:
    _maybe_emit_deploy_event()
    if fault_active("memory-pressure"):
        _LEAK.append(os.urandom(1_000_000))
        if len(_LEAK) % 50 == 0:
            logger.warning("orders heap keeps growing: %d MB retained", len(_LEAK))
    if fault_active("bad-deploy"):
        time.sleep(random.uniform(0.3, 1.2))
        if random.random() < 0.2:
            logger.error("NoneType has no attribute 'sku' while normalizing order payload "
                         "(introduced in 1.1.0-rc1)")
            raise HTTPException(500, "order normalization failed")

    order_id = uuid.uuid4().hex[:12]
    amount = body.quantity * 1999
    try:
        with psycopg.connect(DSN, connect_timeout=5) as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO orders (id, product_id, quantity, amount_cents) "
                "VALUES (%s, %s, %s, %s)",
                (order_id, body.product_id, body.quantity, amount),
            )
    except psycopg.Error as exc:
        logger.error("order insert failed: %s", exc)
        raise HTTPException(500, "orders database error") from exc

    try:
        resp = httpx.post(
            f"{PAYMENTS_URL}/charge",
            json={"order_id": order_id, "amount_cents": amount},
            timeout=10,
        )
    except httpx.HTTPError as exc:
        logger.error("payments call failed for order %s: %s", order_id, exc)
        raise HTTPException(502, "payments unreachable") from exc
    if resp.status_code != 200:
        logger.error("payment failed for order %s: HTTP %s", order_id, resp.status_code)
        raise HTTPException(502, "payment failed")
    return {"order_id": order_id, "status": "paid", "amount_cents": amount}
