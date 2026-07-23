#!/usr/bin/env python3
"""Tiny load generator for Faultline: browses the catalog and checks out
through the gateway so every signal (traces, logs, metrics) flows. Stdlib only.

    python3 loadgen.py [--rps 2] [--duration 300]
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request

GATEWAY = os.getenv("FAULTLINE_GATEWAY", "http://localhost:8090").rstrip("/")


def _get(path: str) -> int:
    try:
        with urllib.request.urlopen(f"{GATEWAY}{path}", timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def _post(path: str, body: dict) -> int:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        f"{GATEWAY}{path}", data=data, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.status
    except urllib.error.HTTPError as exc:
        return exc.code
    except OSError:
        return 0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rps", type=float, default=2.0)
    ap.add_argument("--duration", type=float, default=300.0,
                    help="seconds; 0 = run forever (container mode)")
    args = ap.parse_args()

    deadline = time.time() + (args.duration if args.duration > 0 else 10**9)
    counts: dict[int, int] = {}
    n = 0
    while time.time() < deadline:
        roll = random.random()
        if roll < 0.5:
            status = _get("/api/products")
        elif roll < 0.7:
            status = _get(f"/api/products/{random.randint(1, 10)}")
        else:
            status = _post("/api/checkout",
                           {"product_id": random.randint(1, 10),
                            "quantity": random.randint(1, 3)})
        counts[status] = counts.get(status, 0) + 1
        n += 1
        if n % 25 == 0:
            print(f"[loadgen] {n} requests, status counts: {dict(sorted(counts.items()))}",
                  flush=True)
        time.sleep(max(random.gauss(1.0 / args.rps, 0.1), 0.05))
    print(f"[loadgen] done: {n} requests, {dict(sorted(counts.items()))}")


if __name__ == "__main__":
    main()
