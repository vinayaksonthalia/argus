> **LIVE RUN — July 17 2026 (fix-crew rerun after the trace-dive self-time improvement).** Real Faultline telemetry → real SigNoz alert (rule 019f6cfd…) → real webhook → live Claude (claude-cli, claude-haiku-4-5) → VERIFIED root cause naming the injected pg_sleep(2.5) SELECT at 90% confidence (above the 75% threshold; not flagged). Nothing replayed.

# Postmortem: Faultline catalog p99 latency > 1s — catalog

- **Investigation:** `inv-fcdb95f553`
- **Service:** `catalog`
- **Alert:** `Faultline catalog p99 latency > 1s`
- **Generated:** 2026-07-17 21:02 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 90%

## Root cause
An injected/artificial pg_sleep(2.5) call embedded in the products SELECT statement is directly causing the ~2.5s query latency that drives the p99 breach. — The exact SQL text executed contains 'pg_sleep(2.5)' concatenated into the products query, forcing Postgres to block for 2.5s per call regardless of load; since this is synchronous within the request path, it fully explains the ~2.5s span duration and consequent p99 latency jump, with error_rate unaffected because the query still succeeds. (verified: found 'pg_sleep' in 20 matching rows) [Incident memory: similar to past incident inv-4f5067e229 (similarity 59%) — see 'Similar past incidents'.]

## Impact
p99_latency_ms: 0.0ms before -> 420.1ms after the alert boundary (from ~zero); error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x); throughput_per_min: 0.0req/min before -> 363.2req/min after the alert boundary (from ~zero)

## Timeline
- 20:32:07 UTC — baseline window opens (pre-incident comparison)
- 21:02:07 UTC — alert 'Faultline catalog p99 latency > 1s' started firing
- alert window — p99_latency_ms: 0.0ms before -> 420.1ms after the alert boundary (from ~zero)
- alert window — error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 0.0req/min before -> 363.2req/min after the alert boundary (from ~zero)
- 21:02:38 UTC — ARGUS investigation inv-fcdb95f553 began
- 21:02:57 UTC — hypothesis CONFIRMED: An injected/artificial pg_sleep(2.5) call embedded in the products SELECT statement is directly causing the ~2.5s query latency that drives the p99 breach.

## Evidence
- p99_latency_ms: 0.0ms before -> 420.1ms after the alert boundary (from ~zero) — http://localhost:8080/services/catalog?startTime=1784320327961&endTime=1784322158082
- error_rate: 0.0% before -> 0.0% after the alert boundary (1.0x) — http://localhost:8080/services/catalog?startTime=1784320327961&endTime=1784322158082
- throughput_per_min: 0.0req/min before -> 363.2req/min after the alert boundary (from ~zero) — http://localhost:8080/services/catalog?startTime=1784320327961&endTime=1784322158082
- exemplar trace 17ee59ee7d36ef3d…: culprit span 'SELECT' (service=catalog, 2507ms, error=False) | db.statement=SELECT id, name, price_cents FROM products, pg_sleep(2.5) WHERE id = %s; db.system=postgresql — http://localhost:8080/trace/17ee59ee7d36ef3d52d91c6026b8f2f7?spanId=7234a56140805a64
- exemplar trace 37c23624f830ebc1…: culprit span 'SELECT' (service=catalog, 2507ms, error=False) | db.statement=SELECT id, name, price_cents FROM products, pg_sleep(2.5) WHERE id = %s; db.system=postgresql — http://localhost:8080/trace/37c23624f830ebc1a690124f889f5bf0?spanId=400ce82e012a0168
- exemplar trace 08c1b9698f1c6e43…: culprit span 'SELECT' (service=catalog, 2506ms, error=False) | db.statement=SELECT id, name, price_cents FROM products, pg_sleep(2.5) ORDER BY id LIMIT 20; db.system=postgresql — http://localhost:8080/trace/08c1b9698f1c6e437dd5d02f1889aea1?spanId=f416931cad922b21
- log signature x2 (novel vs prior hour): HTTP Request: GET http://catalog:<*>/products/<*> "HTTP/<*> <*> OK" — http://localhost:8080/logs/logs-explorer?startTime=1784320327961&endTime=1784322158082&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- log signature x1 (novel vs prior hour): HTTP Request: GET http://catalog:<*>/products "HTTP/<*> <*> OK" — http://localhost:8080/logs/logs-explorer?startTime=1784320327961&endTime=1784322158082&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27catalog%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- similar to incident inv-4f5067e229 (Jul 17, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 59%): root cause was: A specific slow child span (e.g., a database query) inside catalog's handling of GET /products is the bottleneck causing the p99 breach. — Within the catalog service's trace, one child span (likely a DB call) dominates total request duration; this would explain why gateway-observed latency for /api/products and /api/products/{id} is ~2.5s while error rate remains 0%, since the request completes su
- similar to incident inv-58c6674b76 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 47%): root cause was: Reduced throughput is a symptom (clients/load balancer backing off or timing out) rather than a cause, and error rate staying flat at 0% rules out timeout/502-driven explanations seen in prior similar incidents. — Because error_rate remained 0.0% before and after (no 502s), the gateway is not aborting due to timeout thresholds being exceeded, distinguishing this incident from the two lower-similar
- similar to incident inv-5736466ee5 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 46%): root cause was: The catalog service's /products endpoint is consistently slow due to an inefficient downstream call or query, independent of load, causing sustained ~2.3s p99 latency. — A fixed-cost slow operation (e.g., unindexed DB query, slow dependency call) on the /products path adds ~2s latency to every request; since latency stayed flat (2278ms->2306ms) even as throughput halved, the slowness is not load-d

## Similar past incidents (ARGUS memory)
- similar to incident inv-4f5067e229 (Jul 17, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 59%): root cause was: A specific slow child span (e.g., a database query) inside catalog's handling of GET /products is the bottleneck causing the p99 breach. — Within the catalog service's trace, one child span (likely a DB call) dominates total request duration; this would explain why gateway-observed latency for /api/products and /api/products/{id} is ~2.5s while error rate remains 0%, since the request completes su
- similar to incident inv-58c6674b76 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 47%): root cause was: Reduced throughput is a symptom (clients/load balancer backing off or timing out) rather than a cause, and error rate staying flat at 0% rules out timeout/502-driven explanations seen in prior similar incidents. — Because error_rate remained 0.0% before and after (no 502s), the gateway is not aborting due to timeout thresholds being exceeded, distinguishing this incident from the two lower-similar
- similar to incident inv-5736466ee5 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 46%): root cause was: The catalog service's /products endpoint is consistently slow due to an inefficient downstream call or query, independent of load, causing sustained ~2.3s p99 latency. — A fixed-cost slow operation (e.g., unindexed DB query, slow dependency call) on the /products path adds ~2s latency to every request; since latency stayed flat (2278ms->2306ms) even as throughput halved, the slowness is not load-d

## Hypotheses considered
- [CONFIRMED] An injected/artificial pg_sleep(2.5) call embedded in the products SELECT statement is directly causing the ~2.5s query latency that drives the p99 breach. — found 'pg_sleep' in 20 matching rows
- [ERROR] The slow DB span dominates total request duration for GET /products and /products/{id}, making the query the fixed-cost bottleneck rather than gateway/network overhead. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- [ERROR] Latency degradation is load-independent (a fixed-cost slow operation), not caused by increased throughput or resource contention. — verification failed to run: Client error '404 Not Found' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/404
- [REFUTED] The novel HTTP log signatures for GET /products and /products/{id} indicate these are newly-active (previously idle) endpoints whose first invocations surface the pre-existing slow query path. — '/products' not found in 0 rows

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 1, tokens: 5700 in / 1470 out, est. $0.0407
- Query footprint: 22 SigNoz queries · 306,252 rows / 33.8 MB scanned · 151 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## Evidence dashboard
- http://localhost:8080/dashboard/019f71e3-bb43-7d9f-bd05-2271da14a26b

## Draft follow-up alert (leading indicator)
- `[DRAFT · ARGUS] catalog: An injected/artificial pg_sleep(2.5) call embedded in the products SELECT statem` — created **disabled**; review and enable: http://localhost:8080/alerts/edit?ruleId=019f71e3-bb57-7c53-8def-90a5ba9fa3cd
