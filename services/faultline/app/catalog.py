"""Catalog service: product listing backed by Postgres.

Fault `slow-query`: wraps the product SELECT in pg_sleep(2.5) — the classic
"a database query got slow" incident. The sleep happens INSIDE Postgres so
the slow span is the DB client span with the offending statement visible in
`db.statement` (exactly what ARGUS's trace dive walks to).
"""

from __future__ import annotations

import logging
import os

import psycopg
from fastapi import HTTPException

from .common import fault_active, make_app

logger = logging.getLogger("faultline.catalog")

DSN = os.getenv(
    "DATABASE_URL", "postgresql://faultline:faultline@localhost:5432/faultline"
)

app = make_app("catalog", ["slow-query"])


def _connect() -> psycopg.Connection:
    return psycopg.connect(DSN, connect_timeout=5)


@app.get("/products")
def products() -> dict:
    try:
        with _connect() as conn, conn.cursor() as cur:
            if fault_active("slow-query"):
                # The injected fault: pg_sleep inside the product query.
                cur.execute(
                    "SELECT id, name, price_cents FROM products, pg_sleep(2.5) "
                    "ORDER BY id LIMIT 20"
                )
            else:
                cur.execute("SELECT id, name, price_cents FROM products ORDER BY id LIMIT 20")
            rows = cur.fetchall()
    except psycopg.Error as exc:
        logger.error("catalog db query failed: %s", exc)
        raise HTTPException(500, "catalog database error") from exc
    return {"products": [{"id": r[0], "name": r[1], "price_cents": r[2]} for r in rows]}


@app.get("/products/{product_id}")
def product(product_id: int) -> dict:
    with _connect() as conn, conn.cursor() as cur:
        if fault_active("slow-query"):
            cur.execute(
                "SELECT id, name, price_cents FROM products, pg_sleep(2.5) WHERE id = %s",
                (product_id,),
            )
        else:
            cur.execute(
                "SELECT id, name, price_cents FROM products WHERE id = %s", (product_id,)
            )
        row = cur.fetchone()
    if not row:
        raise HTTPException(404, "no such product")
    return {"id": row[0], "name": row[1], "price_cents": row[2]}
