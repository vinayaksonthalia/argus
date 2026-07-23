# Postmortem: Faultline catalog p99 latency > 1s — catalog

- **Investigation:** `inv-3a51fe90dd`
- **Service:** `catalog`
- **Alert:** `Faultline catalog p99 latency > 1s`
- **Generated:** 2026-07-16 22:35 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 0%  (DEGRADED: evidence-only)

## Root cause
No hypothesis survived verification. Evidence-only report; human investigation required.

> ⚠ **Flagged for human review** — confidence below threshold (0% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 0.0ms before -> 2940.2ms after the alert boundary (from ~zero); error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x); throughput_per_min: 0.0req/min before -> 59.6req/min after the alert boundary (from ~zero)

## Timeline
- 21:49:07 UTC — baseline window opens (pre-incident comparison)
- 22:19:07 UTC — alert 'Faultline catalog p99 latency > 1s' started firing
- alert window — p99_latency_ms: 0.0ms before -> 2940.2ms after the alert boundary (from ~zero)
- alert window — error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 0.0req/min before -> 59.6req/min after the alert boundary (from ~zero)
- 22:34:38 UTC — ARGUS investigation inv-3a51fe90dd began

## Evidence
- p99_latency_ms: 0.0ms before -> 2940.2ms after the alert boundary (from ~zero) — http://localhost:8080/services/catalog?startTime=1784238547961&endTime=1784241278089
- error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784238547961&endTime=1784241278089
- throughput_per_min: 0.0req/min before -> 59.6req/min after the alert boundary (from ~zero) — http://localhost:8080/services/catalog?startTime=1784238547961&endTime=1784241278089
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- exemplar trace a6f5f04a659f8f4a…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/a6f5f04a659f8f4a610e758c0c32454d?spanId=a0dbfeabd504cb0c
- exemplar trace 20b567758df5c978…: culprit span 'GET /api/products http send' (service=gateway, 0ms, error=True) | http.status_code=502 — http://localhost:8080/trace/20b567758df5c978938500f1ee147d40?spanId=0ab53ca105ac487d
- log signature x3 (novel vs prior hour): upstream call http://catalog:<*>/products failed: timed out — http://localhost:8080/logs/logs-explorer?startTime=1784238547961&endTime=1784241278089&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D

## Hypotheses considered
- [REFUTED] The catalog service is timing out on downstream/internal dependency calls, causing gateway requests to /api/products to hang and eventually fail with 502s. — 'timed out' not found in 0 rows
- [REFUTED] The gateway's timeout configuration for calls to catalog is too aggressive/misconfigured, prematurely returning 502 before catalog fully responds. — 'connection refused' not found in 20 rows
- [ERROR] Catalog service just scaled up from zero and is experiencing cold-start latency (JIT warmup, connection pool/cache initialization), causing p99 to spike and gateway requests to exceed its own timeout, producing 502s. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- [REFUTED] The gateway-to-catalog connection pool is exhausted/saturated, causing new requests to fail immediately (0ms) with 502 before any network call is attempted, independent of catalog's actual processing time. — 'pool exhausted' not found in 0 rows
- [REFUTED] Catalog's /products endpoint is issuing an expensive, unindexed database query that only manifests under real load, causing catalog-side latency to spike once traffic resumed, independent of any gateway misconfiguration. — 20 rows (need > 800.0)
- [REFUTED] The gateway's DNS/service-discovery resolution for 'catalog' is flapping or returning stale/unhealthy endpoints, causing immediate connection failures classified generically as 502 rather than a timeout or refused-connection error. — 'could not resolve' not found in 0 rows

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 2, tokens: 9925 in / 3349 out, est. $0.0775
- Query footprint: 24 SigNoz queries · 264,891 rows / 56.8 MB scanned · 525 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## ARGUS self-diagnosis: why this investigation failed to converge

_Auto-generated analysis of the investigation's own execution (trace `argus.investigation` / `inv-3a51fe90dd` in SigNoz)._

**Evidence sources that returned nothing:**
- infra: infrastructure metrics unavailable for this service
- change_corr: no deployments recorded in the alert window

**Node errors during the run:**
- verify[verify.1.1]: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- verify[verify.2.0]: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404

**Hypotheses proposed and struck down (with the disproving query):**
- The catalog service is timing out on downstream/internal dependency calls, causing gateway requests to /api/products to hang and eventually fail with 502s. — 'timed out' not found in 0 rows
- The gateway's timeout configuration for calls to catalog is too aggressive/misconfigured, prematurely returning 502 before catalog fully responds. — 'connection refused' not found in 20 rows
- Catalog service just scaled up from zero and is experiencing cold-start latency (JIT warmup, connection pool/cache initialization), causing p99 to spike and gateway requests to exceed its own timeout, producing 502s. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- The gateway-to-catalog connection pool is exhausted/saturated, causing new requests to fail immediately (0ms) with 502 before any network call is attempted, independent of catalog's actual processing time. — 'pool exhausted' not found in 0 rows
- Catalog's /products endpoint is issuing an expensive, unindexed database query that only manifests under real load, causing catalog-side latency to spike once traffic resumed, independent of any gateway misconfiguration. — 20 rows (need > 800.0)
- The gateway's DNS/service-discovery resolution for 'catalog' is flapping or returning stale/unhealthy endpoints, causing immediate connection failures classified generically as 502 rather than a timeout or refused-connection error. — 'could not resolve' not found in 0 rows

**Likely failure mode:** every mechanistically plausible hypothesis was falsified by the telemetry — the true cause is outside the collected evidence (consider widening the window or adding infra/change signals).

## Evidence dashboard
- http://localhost:8080/dashboard/019f6d12-0165-7c3c-9c1f-c7c42fd47b42
