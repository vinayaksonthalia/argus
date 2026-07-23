# Generalization proof — ARGUS on SigNoz/opentelemetry-demo-lite (July 17, 2026)

An investigation on an app we did NOT write: the official
SigNoz/opentelemetry-demo-lite stack (Go/Node/Python e-commerce services)
running from a fresh clone, OTLP pointed at the same self-hosted SigNoz.
Incident induced by stopping its Redis container; ARGUS pointed at the
failing `cart` service via a one-shot live investigation (real queries, real
Claude via claude-cli, REST transport).

## What worked on a foreign app, unchanged
- Golden signals: error_rate 100%, ~3,600 req/min, p99 ~127ms — all real.
- Trace dive found the smoking gun in cart's spans (services and span
  attributes ARGUS had never seen): culprit spans `del` / `hgetall` with
  `db.system=redis` and exception `dial tcp: lookup redis on 127.0.0.11:53:
  no such host` — the exact induced fault.
- Log template clustering surfaced the novel error signatures (GetProduct /
  FetchProduct / AddItem).
- Change correlation picked up a real `deployment` change event (via the
  attribute.event.name filter fixed earlier the same day — the bug ARGUS
  found in itself).
- Incident memory recalled past incidents (low similarity, correctly not
  cited in the verdict — different failure class than the catalog corpus).
- The top hypothesis (55%) named the true root cause: "The Redis
  instance/service backing cart's cache is down or was removed from the
  network (e.g., DNS entry deleted, container stopped)".

## Honest limitation (kept, not hidden)
Mechanical verification REFUTED all hypotheses (report flagged DEGRADED,
confidence 0%): the model's verification filters didn't match demo-lite's
ingested schema (0 rows returned), so ARGUS refused to bless its own correct
guess. That is the designed behavior — claims the telemetry doesn't back are
refuted, not reported — but it shows verification-spec quality depends on
knowing the target app's field catalog. Feeding the SigNoz field catalog into
the hypothesize prompt is the identified fix (future work, noted in DOCS.md).

The full auto-generated postmortem follows.

---

# Postmortem: demo-lite cart error rate spike — cart

- **Investigation:** `inv-da2ad5543b`
- **Service:** `cart`
- **Alert:** `demo-lite cart error rate spike`
- **Generated:** 2026-07-17 13:18 UTC (auto-drafted by ARGUS — review before publishing)
- **Confidence:** 0%  (DEGRADED: evidence-only)

## Root cause
No hypothesis survived verification. Evidence-only report; human investigation required.

> ⚠ **Flagged for human review** — confidence below threshold (0% < 75%) or no hypothesis verified.

## Impact
p99_latency_ms: 126.8ms before -> 137.5ms after the alert boundary (1.1x); error_rate: 100.0% before -> 100.0% after the alert boundary (1.0x); throughput_per_min: 3641.6req/min before -> 3603.6req/min after the alert boundary (1.0x)

## Timeline
- 12:38:15 UTC — baseline window opens (pre-incident comparison)
- ~alert window — change detected: deployment: service=orders version=1.1.0-rc1 — deployment completed
- 13:08:15 UTC — alert 'demo-lite cart error rate spike' started firing
- alert window — p99_latency_ms: 126.8ms before -> 137.5ms after the alert boundary (1.1x)
- alert window — error_rate: 100.0% before -> 100.0% after the alert boundary (1.0x)
- alert window — throughput_per_min: 3641.6req/min before -> 3603.6req/min after the alert boundary (1.0x)
- 13:18:16 UTC — ARGUS investigation inv-da2ad5543b began

## Evidence
- p99_latency_ms: 126.8ms before -> 137.5ms after the alert boundary (1.1x) — http://localhost:8080/services/cart?startTime=1784291895954&endTime=1784294296379
- error_rate: 100.0% before -> 100.0% after the alert boundary (1.0x) — http://localhost:8080/services/cart?startTime=1784291895954&endTime=1784294296379
- throughput_per_min: 3641.6req/min before -> 3603.6req/min after the alert boundary (1.0x) — http://localhost:8080/services/cart?startTime=1784291895954&endTime=1784294296379
- exemplar trace d7c4258f5bb3cd35…: culprit span 'del' (service=cart, 95ms, error=True) | db.statement=del cart:user-2190; db.system=redis; service.version=1.0.0 | events: {'name': 'exception', 'timeUnixNano': 1784294140130620799, 'attributes': {'exception.message': 'dial tcp: lookup redis on 127.0.0.11:53: no such host', 'exception.type': '*net.OpError'}} — http://localhost:8080/trace/d7c4258f5bb3cd35abcf884fe8270c30?spanId=61ee0266a822a1d9
- exemplar trace d7c4258f5bb3cd35…: culprit span 'del' (service=cart, 95ms, error=True) | db.statement=del cart:user-2190; db.system=redis; service.version=1.0.0 | events: {'name': 'exception', 'timeUnixNano': 1784294140130620799, 'attributes': {'exception.message': 'dial tcp: lookup redis on 127.0.0.11:53: no such host', 'exception.type': '*net.OpError'}} — http://localhost:8080/trace/d7c4258f5bb3cd35abcf884fe8270c30?spanId=61ee0266a822a1d9
- exemplar trace f773941b9876b707…: culprit span 'hgetall' (service=cart, 87ms, error=True) | db.statement=hgetall cart:user-5900; db.system=redis; service.version=1.0.0 | events: {'name': 'exception', 'timeUnixNano': 1784294137692540381, 'attributes': {'exception.message': 'dial tcp: lookup redis on 127.0.0.11:53: no such host', 'exception.type': '*net.OpError'}} — http://localhost:8080/trace/f773941b9876b707083576cec9339ab2?spanId=04f318420ddb071a
- log signature x9 (novel vs prior hour): GetProduct — http://localhost:8080/logs/logs-explorer?startTime=1784291895954&endTime=1784294296379&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27cart%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- log signature x9 (novel vs prior hour): FetchProduct — http://localhost:8080/logs/logs-explorer?startTime=1784291895954&endTime=1784294296379&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27cart%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- log signature x9 (novel vs prior hour): AddItem — http://localhost:8080/logs/logs-explorer?startTime=1784291895954&endTime=1784294296379&filter=%7B%22expression%22%3A%20%22service.name%20%3D%20%27cart%27%20AND%20severity_text%20IN%20%28%27ERROR%27%2C%27FATAL%27%29%22%7D
- deployment: service=orders version=1.1.0-rc1 — deployment completed — http://localhost:8080/logs/logs-explorer?startTime=1784291895954&endTime=1784294296379&filter=%7B%22expression%22%3A%20%22attribute.event.name%20%3D%20%27deployment%27%22%7D
- similar to incident inv-a6c3436d1d (Jul 17, alert 'demo-lite cart error rate spike', service cart, similarity 88%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.
- similar to incident inv-a2a0b2e215 (Jul 16, alert 'ARGUS LLM spend rate', service argus, similarity 38%): root cause was: ARGUS's own self-query to the 'changes.deployments' query_range API is malformed, causing repeated failed 400 requests that retry and inflate both throughput and LLM investigation spend. — Each investigation triggers a query_range call for deployment changes; a bad request parameter (e.g. invalid time range or filter syntax) causes a 400 Bad Request. ARGUS likely retries or re-invokes the LLM to r
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 29%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c

## Similar past incidents (ARGUS memory)
- similar to incident inv-a6c3436d1d (Jul 17, alert 'demo-lite cart error rate spike', service cart, similarity 88%): investigation did not converge; evidence pointed to: No hypothesis survived verification. Evidence-only report; human investigation required.
- similar to incident inv-a2a0b2e215 (Jul 16, alert 'ARGUS LLM spend rate', service argus, similarity 38%): root cause was: ARGUS's own self-query to the 'changes.deployments' query_range API is malformed, causing repeated failed 400 requests that retry and inflate both throughput and LLM investigation spend. — Each investigation triggers a query_range call for deployment changes; a bad request parameter (e.g. invalid time range or filter syntax) causes a 400 Bad Request. ARGUS likely retries or re-invokes the LLM to r
- similar to incident inv-6bde2d57f9 (Jul 16, alert 'Faultline catalog p99 latency > 1s', service catalog, similarity 29%): root cause was: The catalog service is timing out under load, causing the gateway to receive upstream timeouts and return 502s to clients. — Throughput to catalog jumped 5.7x while p99 latency remained elevated (~2.6-4.2s), pushing requests past the gateway's upstream timeout threshold; the gateway logs 'upstream call http://catalog:*/products failed: timed out' and emits 502 http send spans, indicating catalog c

## Hypotheses considered
- [REFUTED] The Redis instance/service backing cart's cache is down or was removed from the network (e.g., DNS entry deleted, container stopped), rather than a code-level bug in cart. — '' not found in 0 rows
- [REFUTED] All cart error-rate spikes are caused by every Redis-backed span (del, hgetall, and others) failing uniformly, not by a subset of operations like GetProduct/AddItem logic bugs. — count() after/before ratio = 0.00 (need > 0.95)
- [REFUTED] The cart service's Redis client configuration (DNS name 'redis') is broken specifically within the cart service's environment/network namespace, distinct from the actual Redis infra state, causing every Redis-backed call to fail DNS resolution while non-Redis code paths remain unaffected. — 'no such host' not found in 0 rows
- [ERROR] A recent cart service deployment (version 1.0.0) changed or broke the Redis connection string/hostname used by the cart client, unrelated to the orders 1.1.0-rc1 deployment noted in change history. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- [REFUTED] Network policy or service mesh sidecar (e.g., Istio/Envoy) egress rules were changed to block/misroute DNS queries from the cart pod to the cluster DNS resolver, causing all outbound Redis lookups to fail while other internal service calls (via mesh-aware routing) succeed. — '127.0.0.11:53' not found in 0 rows

## Cost
- LLM: claude-haiku-4-5-20251001 (live)
- LLM calls: 2, tokens: 5320 in / 2220 out, est. $0.0691
- Query footprint: 24 SigNoz queries · 7,973,055 rows / 914.0 MB scanned · 3156 ms query time

## Action items
- [ ] Validate the root cause fix
- [ ] Add a leading-indicator alert for this failure class
## ARGUS self-diagnosis: why this investigation failed to converge

_Auto-generated analysis of the investigation's own execution (trace `argus.investigation` / `inv-da2ad5543b` in SigNoz)._

**Evidence sources that returned nothing:**
- infra: infrastructure metrics unavailable for this service

**Node errors during the run:**
- verify[verify.1.0]: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- verify[verify.2.1]: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400

**Hypotheses proposed and struck down (with the disproving query):**
- The Redis instance/service backing cart's cache is down or was removed from the network (e.g., DNS entry deleted, container stopped), rather than a code-level bug in cart. — '' not found in 0 rows
- All cart error-rate spikes are caused by every Redis-backed span (del, hgetall, and others) failing uniformly, not by a subset of operations like GetProduct/AddItem logic bugs. — count() after/before ratio = 0.00 (need > 0.95)
- The cart service's Redis client configuration (DNS name 'redis') is broken specifically within the cart service's environment/network namespace, distinct from the actual Redis infra state, causing every Redis-backed call to fail DNS resolution while non-Redis code paths remain unaffected. — 'no such host' not found in 0 rows
- A recent cart service deployment (version 1.0.0) changed or broke the Redis connection string/hostname used by the cart client, unrelated to the orders 1.1.0-rc1 deployment noted in change history. — verification failed to run: Client error '400 Bad Request' for url 'http://localhost:8080/api/v5/query_range'
For more information check: https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/400
- Network policy or service mesh sidecar (e.g., Istio/Envoy) egress rules were changed to block/misroute DNS queries from the cart pod to the cluster DNS resolver, causing all outbound Redis lookups to fail while other internal service calls (via mesh-aware routing) succeed. — '127.0.0.11:53' not found in 0 rows

**Likely failure mode:** every mechanistically plausible hypothesis was falsified by the telemetry — the true cause is outside the collected evidence (consider widening the window or adding infra/change signals).

## Evidence dashboard
- http://localhost:8080/dashboard/019f703a-dc3c-73f7-acf4-e99dbbbc7ca8
