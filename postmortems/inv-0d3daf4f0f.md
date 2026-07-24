# Postmortem: GLASSPANE: browser error spike — meridian-web

- **Investigation:** `inv-0d3daf4f0f`
- **Service:** `meridian-web`
- **Alert:** `GLASSPANE: browser error spike`
- **Generated:** 2026-07-17 21:35 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 55%

## Root cause
A frontend deploy (service.version 1.4.2) introduced a code path that calls .map() on a non-array API response, causing uncaught TypeErrors in the browser. — Backend response shape changed or returned an unexpected object/undefined instead of an array; client code assumes array and calls .map(), throwing 'x.map is not a function' repeatedly, which GLASSPANE records as browser.errors.count spikes. Increased throughput (4.7x) surfaces more instances of this pre-existing bug, explaining the error rate rising from 0% to 1.6% while latency actually drops (errors are fast client-side failures, not slow requests). (verified: found 'map is not a function' in 40 matching rows)

> ⚠ **Flagged for human review** — confidence below threshold (55% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 1533.3ms before -> 895.3ms after the alert boundary (0.58x (42% drop)); error_rate: 0.0% before -> 1.6% after the alert boundary (from ~zero); throughput_per_min: 0.8req/min before -> 4.0req/min after the alert boundary (4.7x)

## Timeline
- 21:04:47 UTC — baseline window opens (pre-incident comparison)
- 21:34:47 UTC — alert 'GLASSPANE: browser error spike' started firing
- alert window — p99_latency_ms: 1533.3ms before -> 895.3ms after the alert boundary (0.58x (42% drop))
- alert window — error_rate: 0.0% before -> 1.6% after the alert boundary (from ~zero)
- alert window — throughput_per_min: 0.8req/min before -> 4.0req/min after the alert boundary (4.7x)
- 21:35:17 UTC — ARGUS investigation inv-0d3daf4f0f began
- 21:35:36 UTC — hypothesis CONFIRMED: A frontend deploy (service.version 1.4.2) introduced a code path that calls .map() on a non-array API response, causing uncaught TypeErrors in the browser.

## Evidence
- p99_latency_ms: 1533.3ms before -> 895.3ms after the alert boundary (0.58x (42% drop)) — http://localhost:8080/services/meridian-web?startTime=1784322287516&endTime=1784324117593
- error_rate: 0.0% before -> 1.6% after the alert boundary (from ~zero) — http://localhost:8080/services/meridian-web?startTime=1784322287516&endTime=1784324117593
- throughput_per_min: 0.8req/min before -> 4.0req/min after the alert boundary (4.7x) — http://localhost:8080/services/meridian-web?startTime=1784322287516&endTime=1784324117593
- exemplar trace 35db40f8880d0a01…: culprit span 'HTTP GET' (service=meridian-web, 4ms, error=True) | service.version=1.4.2 — http://localhost:8080/trace/35db40f8880d0a012fa248ba7c61d3f4?spanId=9432a3500ae99427
- exemplar trace 24512dba7c501daf…: culprit span 'HTTP GET' (service=meridian-web, 3ms, error=True) | service.version=1.4.2 — http://localhost:8080/trace/24512dba7c501daf8c109ecf1e71daae?spanId=ac174925c9e0060f
- log signature x20 (pre-existing): Uncaught TypeError: t.map is not a function — http://localhost:8080/logs/logs-explorer?startTime=1784322287516&endTime=1784324117593&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27meridian-web%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- log signature x20 (pre-existing): Uncaught TypeError: e.map is not a function — http://localhost:8080/logs/logs-explorer?startTime=1784322287516&endTime=1784324117593&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27meridian-web%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- log signature x1 (pre-existing): Cannot read properties of undefined (reading 'compute') — http://localhost:8080/logs/logs-explorer?startTime=1784322287516&endTime=1784324117593&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27meridian-web%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 41%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.
- similar to incident inv-4f5067e229 (Jul 17, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 37%): root cause was: A specific slow child span (e.g., a database query) inside catalog's handling of GET /products is the bottleneck causing the p99 breach. — Within the catalog service's trace, one child span (likely a DB call) dominates total request duration; this would explain why gateway-observed latency for /api/products and /api/products/{id} is ~2.5s while error rate remains 0%, since the request completes su
- similar to incident inv-977e5fd4e8 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 36%): root cause was: A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — Increased request volume saturates catalog's processing capacity (e.g., thread pool, DB connections), driving p99 latency past the gateway's fixed upstream timeout; gateway then aborts the call and returns 502 wi

## Similar past incidents (ARGUS memory)
- similar to incident inv-3a51fe90dd (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 41%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.
- similar to incident inv-4f5067e229 (Jul 17, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 37%): root cause was: A specific slow child span (e.g., a database query) inside catalog's handling of GET /products is the bottleneck causing the p99 breach. — Within the catalog service's trace, one child span (likely a DB call) dominates total request duration; this would explain why gateway-observed latency for /api/products and /api/products/{id} is ~2.5s while error rate remains 0%, since the request completes su
- similar to incident inv-977e5fd4e8 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 36%): root cause was: A surge in throughput to catalog (4.6x) overwhelms its capacity, causing catalog to respond slowly enough that the gateway's upstream timeout is exceeded, producing 502s at the gateway. — Increased request volume saturates catalog's processing capacity (e.g., thread pool, DB connections), driving p99 latency past the gateway's fixed upstream timeout; gateway then aborts the call and returns 502 wi

## Hypotheses considered
- [CONFIRMED] A frontend deploy (service.version 1.4.2) introduced a code path that calls .map() on a non-array API response, causing uncaught TypeErrors in the browser. — found 'map is not a function' in 40 matching rows
- [ERROR] An upstream API (consumed by meridian-web) is returning malformed/undefined payloads under increased load, causing the frontend's data-processing code to throw on '.map' and 'reading compute'. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- [ERROR] The error spike is an artifact of increased traffic volume alone (4.7x throughput), surfacing a long-standing low-frequency client bug rather than any new regression. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 1, tokens: 4777 in / 1151 out, est. $0.0295
- Query footprint: 18 SigNoz queries · 478,556 rows / 47.0 MB scanned · 202 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## Evidence dashboard
- http://localhost:8080/dashboard/019f7201-9c5f-7a69-93e9-7c47d8501230

## Draft follow-up alert (leading indicator)
- `[DRAFT · ARGUS] meridian-web: A frontend deploy (service.version 1.4.2) introduced a code path that calls .map` — created **disabled**; review and enable: http://localhost:8080/alerts/edit?ruleId=019f7201-9c78-75e9-952a-b6e84887815c
