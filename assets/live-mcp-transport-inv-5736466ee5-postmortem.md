# Postmortem: Faultline catalog p99 latency > 1s — catalog

- **Investigation:** `inv-5736466ee5`
- **Service:** `catalog`
- **Alert:** `Faultline catalog p99 latency > 1s`
- **Generated:** 2026-07-16 23:21 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 55%

## Root cause
The catalog service's /products endpoint is consistently slow due to an inefficient downstream call or query, independent of load, causing sustained ~2.3s p99 latency. — A fixed-cost slow operation (e.g., unindexed DB query, slow dependency call) on the /products path adds ~2s latency to every request; since latency stayed flat (2278ms->2306ms) even as throughput halved, the slowness is not load-driven but inherent to the request path itself. (verified: found 'db' in 20 matching rows) [Incident memory: similar to past incident inv-977e5fd4e8 (similarity 57%) — see 'Similar past incidents'.]

> ⚠ **Flagged for human review** — confidence below threshold (55% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 2278.5ms before -> 2306.6ms after the alert boundary (1.0x); error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x); throughput_per_min: 99.5req/min before -> 50.1req/min after the alert boundary (0.5x)

## Timeline
- 22:51:26 UTC — baseline window opens (pre-incident comparison)
- 23:21:26 UTC — alert 'Faultline catalog p99 latency > 1s' started firing
- alert window — p99_latency_ms: 2278.5ms before -> 2306.6ms after the alert boundary (1.0x)
- alert window — error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 99.5req/min before -> 50.1req/min after the alert boundary (0.5x)
- 23:21:39 UTC — ARGUS investigation inv-5736466ee5 began
- 23:21:58 UTC — hypothesis CONFIRMED: The catalog service's /products endpoint is consistently slow due to an inefficient downstream call or query, independent of load, causing sustained ~2.3s p99 latency.

## Evidence
- p99_latency_ms: 2278.5ms before -> 2306.6ms after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784242286450&endTime=1784244099931
- error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784242286450&endTime=1784244099931
- throughput_per_min: 99.5req/min before -> 50.1req/min after the alert boundary (0.5x) — http://localhost:8080/services/catalog?startTime=1784242286450&endTime=1784244099931
- exemplar trace f13670a6f1f7d788…: culprit span 'GET /api/products' (service=gateway, 2648ms, error=False) | http.route=/api/products; http.status_code=200; http.url=http://localhost:8090/api/products — http://localhost:8080/trace/f13670a6f1f7d78807dd7fa31c27aa79?spanId=980164cfbb8d72eb
- exemplar trace f511375bfe50f6e7…: culprit span 'GET /api/products' (service=gateway, 2557ms, error=False) | http.route=/api/products; http.status_code=200; http.url=http://localhost:8090/api/products — http://localhost:8080/trace/f511375bfe50f6e777c6127cb0d1a112?spanId=c75bfd4452ae5204
- exemplar trace 6953a3d02fd98e69…: culprit span 'GET /api/products' (service=gateway, 2555ms, error=False) | http.route=/api/products; http.status_code=200; http.url=http://localhost:8090/api/products — http://localhost:8080/trace/6953a3d02fd98e6970115b1d4d40e5ef?spanId=ae2dd17bdb28b99b
- log signature x3 (novel vs prior hour): HTTP Request: GET http://catalog:<*>/products "HTTP/<*> <*> OK" — http://localhost:8080/logs/logs-explorer?startTime=1784242286450&endTime=1784244099931&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- similar to incident inv-977e5fd4e8 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 57%): root cause was: A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — Increased request volume saturates catalog's processing capacity (e.g., thread pool, DB connections), driving p99 latency past the gateway's fixed upstream timeout; gateway then aborts the call and returns 502 wi
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 55%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 54%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.

## Similar past incidents (ARGUS memory)
- similar to incident inv-977e5fd4e8 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 57%): root cause was: A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — Increased request volume saturates catalog's processing capacity (e.g., thread pool, DB connections), driving p99 latency past the gateway's fixed upstream timeout; gateway then aborts the call and returns 502 wi
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 55%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 54%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.

## Hypotheses considered
- [CONFIRMED] The catalog service's /products endpoint is consistently slow due to an inefficient downstream call or query, independent of load, causing sustained ~2.3s p99 latency. — found 'db' in 20 matching rows
- [REFUTED] Catalog is degraded due to resource exhaustion (e.g., connection pool or thread pool saturation) that persists even as throughput drops, unlike prior incidents where a throughput surge caused the saturation. — 'pool' not found in 3 rows
- [REFUTED] The gateway is timing out or retrying against catalog, artificially reducing observed catalog throughput while catalog itself remains slow, mirroring prior 502-timeout incidents but without yet crossing the timeout threshold. — count() = 0.00 (need > 0.0)

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 1, tokens: 4715 in / 1146 out, est. $0.0290
- Query footprint: 22 SigNoz queries · 8,572,558 rows / 1235.3 MB scanned · 20586 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## Evidence dashboard
- http://localhost:8080/dashboard/019f6d3c-a4b2-78f8-852e-766d4f7e2256

## Draft follow-up alert (leading indicator)
- `[DRAFT · ARGUS] catalog: The catalog service's /products endpoint is consistently slow due to an ineffici` — created **disabled**; review and enable: http://localhost:8080/alerts/edit?ruleId=019f6d3c-a4d0-7985-b507-9b2f04483e26
