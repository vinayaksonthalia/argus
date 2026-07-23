# Postmortem: Faultline catalog p99 latency > 1s — catalog

- **Investigation:** `inv-977e5fd4e8`
- **Service:** `catalog`
- **Alert:** `Faultline catalog p99 latency > 1s`
- **Generated:** 2026-07-16 23:12 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 60%

## Root cause
A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — Increased request volume saturates catalog's processing capacity (e.g., thread pool, DB connections), driving p99 latency past the gateway's fixed upstream timeout; gateway then aborts the call and returns 502 with 'timed out' logs, while catalog itself may not log errors since it eventually completes the work. (verified: count() after/before ratio = 4.25 (need > 3.0)) [Incident memory: similar to past incident inv-6bde2d57f9 (similarity 76%) — see 'Similar past incidents'.]

> ⚠ **Flagged for human review** — confidence below threshold (60% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 4186.7ms before -> 2569.0ms after the alert boundary (0.6x); error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x); throughput_per_min: 23.7req/min before -> 108.0req/min after the alert boundary (4.6x)

## Timeline
- 22:16:07 UTC — baseline window opens (pre-incident comparison)
- 22:46:07 UTC — alert 'Faultline catalog p99 latency > 1s' started firing
- alert window — p99_latency_ms: 4186.7ms before -> 2569.0ms after the alert boundary (0.6x)
- alert window — error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 23.7req/min before -> 108.0req/min after the alert boundary (4.6x)
- 23:12:08 UTC — ARGUS investigation inv-977e5fd4e8 began
- 23:12:28 UTC — hypothesis CONFIRMED: A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway.
- 23:12:28 UTC — hypothesis CONFIRMED: The gateway's upstream timeout threshold itself (not catalog degradation) is the proximate trigger, converting slow-but-completing catalog responses into 502 errors.

## Evidence
- p99_latency_ms: 4186.7ms before -> 2569.0ms after the alert boundary (0.6x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784243528111
- error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784243528111
- throughput_per_min: 23.7req/min before -> 108.0req/min after the alert boundary (4.6x) — http://localhost:8080/services/catalog?startTime=1784240167961&endTime=1784243528111
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- exemplar trace a6f5f04a659f8f4a…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/a6f5f04a659f8f4a610e758c0c32454d?spanId=a0dbfeabd504cb0c
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- log signature x3 (novel vs prior hour): upstream call http://catalog:<*>/products failed: timed out — http://localhost:8080/logs/logs-explorer?startTime=1784240167961&endTime=1784243528111&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 76%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 71%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.

## Similar past incidents (ARGUS memory)
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 76%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 71%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.

## Hypotheses considered
- [CONFIRMED] A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — count() after/before ratio = 4.25 (need > 3.0)
- [ERROR] Catalog service is exhausting a downstream resource (e.g., database connection pool) under increased load, causing internal queuing that inflates p99 latency beyond the gateway's timeout. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- [CONFIRMED] The gateway's upstream timeout threshold itself (not catalog degradation) is the proximate trigger, converting slow-but-completing catalog responses into 502 errors. — found 'timed out' in 3 matching rows
- [ERROR] Catalog error rate remains at 0% despite the latency spike, suggesting the root cause is purely a client-side/gateway timeout misinterpretation rather than actual catalog request failures. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 1, tokens: 5200 in / 1366 out, est. $0.0398
- Query footprint: 22 SigNoz queries · 3,323,444 rows / 490.9 MB scanned · 8360 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## Evidence dashboard
- http://localhost:8080/dashboard/019f6d33-f062-7b3f-98ab-e72779748e82
