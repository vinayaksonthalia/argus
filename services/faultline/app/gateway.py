"""Gateway: the public edge. Fans out to catalog and orders so every user
request produces a multi-service trace (gateway → catalog → postgres,
gateway → orders → payments)."""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import HTTPException
from pydantic import BaseModel

from .common import make_app

logger = logging.getLogger("faultline.gateway")

CATALOG_URL = os.getenv("CATALOG_URL", "http://localhost:8091")
ORDERS_URL = os.getenv("ORDERS_URL", "http://localhost:8093")

app = make_app("gateway", [])


class CheckoutRequest(BaseModel):
    product_id: int
    quantity: int = 1


def _proxy(method: str, url: str, **kwargs) -> httpx.Response:
    try:
        resp = httpx.request(method, url, timeout=15, **kwargs)
    except httpx.HTTPError as exc:
        logger.error("upstream call %s failed: %s", url, exc)
        raise HTTPException(502, "upstream unreachable") from exc
    if resp.status_code >= 500:
        logger.error("upstream %s returned HTTP %s", url, resp.status_code)
        raise HTTPException(502, "upstream error")
    return resp


@app.get("/api/products")
def api_products() -> dict:
    return _proxy("GET", f"{CATALOG_URL}/products").json()


@app.get("/api/products/{product_id}")
def api_product(product_id: int) -> dict:
    resp = _proxy("GET", f"{CATALOG_URL}/products/{product_id}")
    if resp.status_code == 404:
        raise HTTPException(404, "no such product")
    return resp.json()


@app.post("/api/checkout")
def api_checkout(body: CheckoutRequest) -> dict:
    return _proxy("POST", f"{ORDERS_URL}/orders", json=body.model_dump()).json()
