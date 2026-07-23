# Postmortem: Faultline catalog p99 latency > 1s — catalog

- **Investigation:** `inv-6bde2d57f9`
- **Service:** `catalog`
- **Alert:** `Faultline catalog p99 latency > 1s`
- **Generated:** 2026-07-16 22:47 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 60%

## Root cause
The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog cannot keep up with the increased request rate. (verified: found 'timed out' in 3 matching rows)

> ⚠ **Flagged for human review** — confidence below threshold (60% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 4186.7ms before -> 2601.6ms after the alert boundary (0.6x); error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x); throughput_per_min: 23.7req/min before -> 136.4req/min after the alert boundary (5.7x)

## Timeline
- 22:16:07 UTC — baseline window opens (pre-incident comparison)
- 22:46:07 UTC — alert 'Faultline catalog p99 latency > 1s' started firing
- alert window — p99_latency_ms: 4186.7ms before -> 2601.6ms after the alert boundary (0.6x)
- alert window — error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 23.7req/min before -> 136.4req/min after the alert boundary (5.7x)
- 22:47:08 UTC — ARGUS investigation inv-6bde2d57f9 began
- 22:47:27 UTC — hypothesis CONFIRMED: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients.

## Evidence
- p99_latency_ms: 4186.7ms before -> 2601.6ms after the alert boundary (0.6x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784242028076
- error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784242028076
- throughput_per_min: 23.7req/min before -> 136.4req/min after the alert boundary (5.7x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784242028076
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- exemplar trace a6f5f04a659f8f4a…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/a6f5f04a659f8f4a610e758c0c32454d?spanId=a0dbfeabd504cb0c
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- log signature x3 (novel vs prior hour): upstream call http://catalog:<*>/products failed: timed out — http://localhost:8080/logs/logs-explorer?startTime=1784240167961&endTime=1784242028076&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D

## Hypotheses considered
- [CONFIRMED] The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — found 'timed out' in 3 matching rows
- [ERROR] Catalog's /products endpoint itself is the latency bottleneck (e.g., slow downstream dependency or resource saturation), not the gateway. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- [ERROR] A sudden 5.7x surge in request throughput to catalog overwhelmed available capacity (e.g., connection pool or worker exhaustion), causing queuing delays that manifest as timeouts. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- [REFUTED] The gateway's outbound HTTP client/connection pool to catalog is saturated, causing 502s independent of catalog's actual processing time. — 'connection' not found in 5 rows

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 1, tokens: 4864 in / 1468 out, est. $0.0350
- Query footprint: 21 SigNoz queries · 825,207 rows / 128.5 MB scanned · 1888 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## Evidence dashboard
- http://localhost:8080/dashboard/019f6d1d-0b76-785a-8d51-71cb735d6c3b
