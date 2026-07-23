"""Payments service.

Fault `error-storm`: ~30% of /charge calls return 502 with an upstream-style
error log — the "downstream dependency melting down" incident.
"""

from __future__ import annotations

import logging
import random
import time

from fastapi import HTTPException
from pydantic import BaseModel

from .common import fault_active, make_app

logger = logging.getLogger("faultline.payments")

app = make_app("payments", ["error-storm"])


class Charge(BaseModel):
    order_id: str
    amount_cents: int


@app.post("/charge")
def charge(body: Charge) -> dict:
    time.sleep(random.uniform(0.01, 0.05))
    if fault_active("error-storm") and random.random() < 0.3:
        logger.error(
            "payment provider gateway returned 502 Bad Gateway for order %s "
            "(upstream connection reset by peer)", body.order_id,
        )
        raise HTTPException(502, "payment provider unavailable")
    return {"order_id": body.order_id, "charged_cents": body.amount_cents, "status": "captured"}
