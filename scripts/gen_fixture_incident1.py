"""Generate fixtures/incident-1 — a recorded 'slow-db' incident in the
`catalog` service of the Faultline demo mesh.

Response envelopes mirror the real SigNoz v5 /api/v5/query_range shape
(verified against a live SigNoz Community instance). Run from the repo root:

    python scripts/gen_fixture_incident1.py
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIX = ROOT / "fixtures" / "incident-1"

# The incident timeline (fixed for reproducibility).
T0 = datetime(2026, 7, 14, 2, 12, 0, tzinfo=timezone.utc)  # alert startsAt


def ts_ms(dt: datetime) -> int:
    return int(dt.timestamp() * 1000)


def time_series(points: list[tuple[datetime, float]], query: str = "A") -> dict:
    return {
        "status": "success",
        "data": {
            "type": "time_series",
            "meta": {"rowsScanned": 1000, "bytesScanned": 10000, "durationMs": 12},
            "data": {
                "results": [
                    {
                        "queryName": query,
                        "aggregations": [
                            {
                                "index": 0,
                                "series": [
                                    {
                                        "labels": [],
                                        "values": [
                                            {"timestamp": ts_ms(t), "value": v}
                                            for t, v in points
                                        ],
                                    }
                                ],
                            }
                        ],
                    }
                ]
            },
        },
    }


def multi_time_series(by_query: dict[str, list[tuple[datetime, float]]]) -> dict:
    results = []
    for query, points in by_query.items():
        results.append(
            {
                "queryName": query,
                "aggregations": [
                    {
                        "index": 0,
                        "series": [
                            {
                                "labels": [],
                                "values": [
                                    {"timestamp": ts_ms(t), "value": v} for t, v in points
                                ],
                            }
                        ],
                    }
                ],
            }
        )
    return {
        "status": "success",
        "data": {"type": "time_series", "data": {"results": results}},
    }


def raw(rows: list[dict], query: str = "A") -> dict:
    return {
        "status": "success",
        "data": {
            "type": "raw",
            "data": {
                "results": [
                    {
                        "queryName": query,
                        "rows": [
                            {"timestamp": row.get("timestamp", ts_ms(T0)), "data": row}
                            for row in rows
                        ],
                    }
                ]
            },
        },
    }


def minutes(base: datetime, values: list[float], step_min: int = 5) -> list[tuple[datetime, float]]:
    return [(base + timedelta(minutes=i * step_min), v) for i, v in enumerate(values)]


def write(name: str, payload: dict) -> None:
    path = FIX / "responses" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2))


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- alert
    (FIX / "alert.json").write_text(json.dumps({
        "receiver": "argus",
        "status": "firing",
        "alerts": [{
            "status": "firing",
            "labels": {
                "alertname": "CatalogP99LatencyAnomaly",
                "service.name": "catalog",
                "severity": "critical",
                "ruleId": "42",
            },
            "annotations": {
                "summary": "p99 latency for catalog breached the anomaly band",
                "description": "seasonal-decomposition anomaly on p99(duration_nano), catalog service",
            },
            "startsAt": T0.isoformat(),
            "fingerprint": "9a1c22e7c001f5d4",
        }],
        "groupLabels": {"alertname": "CatalogP99LatencyAnomaly"},
        "commonLabels": {"service.name": "catalog"},
        "externalURL": "http://localhost:8080",
        "version": "4",
    }, indent=2))

    before_base = T0 - timedelta(minutes=90)
    after_base = T0 - timedelta(minutes=30)

    # ------------------------------------------------- golden signals (ns / counts)
    write("golden.p99.before", time_series(minutes(before_base, [118e6, 122e6, 119e6, 125e6, 121e6, 120e6])))
    write("golden.p99.after", time_series(minutes(after_base, [130e6, 210e6, 1450e6, 2890e6, 3100e6, 2960e6])))
    write("golden.error_rate.before", multi_time_series({
        "A": minutes(before_base, [0, 1, 0, 0, 1, 0]),
        "B": minutes(before_base, [640, 655, 648, 660, 651, 645]),
    }))
    write("golden.error_rate.after", multi_time_series({
        "A": minutes(after_base, [1, 4, 55, 162, 178, 171]),
        "B": minutes(after_base, [650, 644, 590, 471, 452, 460]),
    }))
    write("golden.throughput.before", time_series(minutes(before_base, [640, 655, 648, 660, 651, 645])))
    write("golden.throughput.after", time_series(minutes(after_base, [650, 644, 590, 471, 452, 460])))

    # ------------------------------------------------- exemplar traces
    trace1, trace2 = "7f3a9c1e5b2d48a6b1c9d0e2f4a67788", "1c8e2b4d6f9a3057c2d4e6f8a0b1c2d3"
    write("traces.search", raw([
        {"trace_id": trace1, "span_id": "aa11bb22cc33dd44", "name": "GET /products",
         "service.name": "catalog", "duration_nano": 3.05e9, "has_error": True},
        {"trace_id": trace2, "span_id": "ee55ff66aa77bb88", "name": "GET /products",
         "service.name": "catalog", "duration_nano": 2.87e9, "has_error": True},
    ]))
    write("traces.detail.0", raw([
        {"trace_id": trace1, "span_id": "0a0a0a0a0a0a0a0a", "name": "GET /checkout",
         "service.name": "gateway", "duration_nano": 3.20e9, "has_error": True},
        {"trace_id": trace1, "span_id": "aa11bb22cc33dd44", "name": "GET /products",
         "service.name": "catalog", "duration_nano": 3.05e9, "has_error": True,
         "http.route": "/products", "http.status_code": 500},
        {"trace_id": trace1, "span_id": "b1b1b1b1b1b1b1b1", "name": "SELECT products",
         "service.name": "catalog", "duration_nano": 2.98e9, "has_error": True,
         "db.system": "postgresql",
         "db.statement": "SELECT *, pg_sleep(2.5) FROM products WHERE category = $1",
         "exception.type": "QueryCanceledError",
         "exception.message": "canceling statement due to statement timeout"},
    ]))
    write("traces.detail.1", raw([
        {"trace_id": trace2, "span_id": "c2c2c2c2c2c2c2c2", "name": "GET /products",
         "service.name": "catalog", "duration_nano": 2.87e9, "has_error": True,
         "http.route": "/products", "http.status_code": 500},
        {"trace_id": trace2, "span_id": "d3d3d3d3d3d3d3d3", "name": "SELECT products",
         "service.name": "catalog", "duration_nano": 2.79e9, "has_error": True,
         "db.system": "postgresql",
         "db.statement": "SELECT *, pg_sleep(2.5) FROM products WHERE category = $1",
         "exception.type": "QueryCanceledError",
         "exception.message": "canceling statement due to statement timeout"},
    ]))

    # ------------------------------------------------- logs
    def log_row(body: str, minute: int, trace_id: str = "") -> dict:
        return {
            "timestamp": ts_ms(T0 + timedelta(minutes=minute)),
            "body": body,
            "severity_text": "ERROR",
            "service.name": "catalog",
            **({"trace_id": trace_id} if trace_id else {}),
        }

    slow_bodies = [
        log_row("db query timeout after 3000 ms executing SELECT products (statement timeout)", 2, trace1),
        log_row("db query timeout after 3000 ms executing SELECT products (statement timeout)", 4, trace2),
        log_row("db query timeout after 3000 ms executing SELECT products (statement timeout)", 6),
        log_row("connection pool exhausted: 20/20 connections busy for 1842 ms", 7),
        log_row("connection pool exhausted: 20/20 connections busy for 2201 ms", 9),
    ]
    write("logs.errors.current", raw(slow_bodies))
    write("logs.errors.prior", raw([
        log_row("cache miss for product 4471, falling back to db", -70),
    ]))
    write("logs.trace.0", raw([slow_bodies[0]]))
    write("logs.trace.1", raw([slow_bodies[1]]))

    # ------------------------------------------------- verification responses
    # H1 (confirmed): p99 of catalog postgres spans jumped >3x across the boundary.
    write("verify.1.0.before", time_series(minutes(before_base, [42e6, 45e6, 44e6, 43e6, 46e6, 44e6])))
    write("verify.1.0.after", time_series(minutes(after_base, [50e6, 180e6, 2410e6, 2860e6, 2950e6, 2900e6])))
    # H2 (refuted): no downstream 502s from payments in catalog's window.
    write("verify.1.1", raw([]))
    # H3 (refuted): error logs contain timeouts, but no OutOfMemory mention.
    write("verify.1.2", raw(slow_bodies))

    # Evidence sources that were unavailable when this incident was recorded.
    (FIX / "optional_missing.json").write_text(json.dumps([
        "infra.k8s_container_memory_usage",
        "infra.k8s_container_cpu_usage",
        "infra.k8s_container_restarts",
        "changes.deployments",
    ], indent=2))

    # ------------------------------------------------- recorded LLM output
    hypotheses = [
        {
            "claim": "Catalog's PostgreSQL product queries became pathologically slow (an injected pg_sleep(2.5) in the SELECT), driving p99 latency and statement timeouts",
            "mechanism": "Every /products request runs the slow SELECT; at ~650 req/min the connection pool saturates, requests queue past the 3000 ms statement timeout and fail with 500s, which matches the p99 jump and error-rate rise at the alert boundary",
            "confidence": 0.9,
            "verification": {
                "kind": "query_range",
                "params": {
                    "signal": "traces",
                    "aggregation": "p99(duration_nano)",
                    "filter_expression": "service.name = 'catalog' AND db.system = 'postgresql'",
                },
                "expected": {
                    "op": "ratio_gt",
                    "value": 3,
                    "description": "p99 of catalog DB spans jumped more than 3x across the alert boundary",
                },
            },
        },
        {
            "claim": "A downstream dependency (payments) is returning 502s, cascading errors into catalog",
            "mechanism": "If payments were failing, catalog error logs would contain upstream 502 responses in the alert window",
            "confidence": 0.35,
            "verification": {
                "kind": "log_check",
                "params": {
                    "signal": "logs",
                    "filter_expression": "service.name = 'catalog' AND severity_text = 'ERROR'",
                },
                "expected": {
                    "op": "contains",
                    "value": "502",
                    "description": "catalog error logs mention upstream 502 responses",
                },
            },
        },
        {
            "claim": "The catalog container is under memory pressure causing GC pauses and slow responses",
            "mechanism": "Memory saturation would show elevated container memory usage in the alert window",
            "confidence": 0.2,
            "verification": {
                "kind": "log_check",
                "params": {
                    "signal": "logs",
                    "filter_expression": "service.name = 'catalog' AND severity_text IN ('ERROR','FATAL')",
                },
                "expected": {
                    "op": "contains",
                    "value": "OutOfMemory",
                    "description": "catalog error logs mention memory exhaustion / OOM",
                },
            },
        },
    ]
    llm_dir = FIX / "llm"
    llm_dir.mkdir(exist_ok=True)
    (llm_dir / "hypothesize.1.json").write_text(json.dumps({
        "text": json.dumps(hypotheses, indent=2),
        "model": "claude-sonnet-4-5",
        "input_tokens": 3184,
        "output_tokens": 612,
    }, indent=2))

    # ------------------------------------------------- ground truth for evals
    (FIX / "ground_truth.json").write_text(json.dumps({
        "scenario": "slow-db",
        "description": "Injected pg_sleep(2.5) in catalog product SELECT; pool exhaustion + statement timeouts",
        "expected_service": "catalog",
        "root_cause_keywords": ["pg_sleep", "postgres", "catalog"],
        "min_confirmed_hypotheses": 1,
        "max_cost_usd": 0.15,
    }, indent=2))

    print(f"fixture written to {FIX}")


if __name__ == "__main__":
    main()
