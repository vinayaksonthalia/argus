# Faultline — ARGUS's demo microservice stack with injectable faults

Four tiny FastAPI services with realistic, *distinguishable* failure modes so
ARGUS's investigations can be demonstrated (and recorded as eval fixtures)
against real telemetry:

```
gateway :8090 ──▶ catalog :8091 ──▶ Postgres :5433
      └─────────▶ orders  :8093 ──▶ payments :8092
                        └──────────▶ Postgres
```

All services are OTel auto-instrumented (`opentelemetry-instrument`) and ship
traces + logs + metrics over OTLP gRPC to the host's SigNoz collector
(`host.docker.internal:4317`), tagged `deployment.environment=faultline`.

## Run

```bash
docker compose up -d --build      # stack + seeded Postgres
python3 loadgen.py --rps 2 --duration 1800 &   # background traffic
```

## Faults (`./faultctl`)

| fault | service | what happens | root cause ARGUS should find |
|---|---|---|---|
| `slow-query` | catalog | product SELECT gains a `pg_sleep(2.5)` cross join | the slow DB span with the statement in `db.statement` |
| `error-storm` | payments | 30% of `/charge` return 502 + upstream-reset error log | downstream payment-provider failure |
| `memory-pressure` | orders | ~1 MB leaked per request + heap-growth warnings | memory trend |
| `bad-deploy` | orders | emits a `deployment` change-event log, then slow/flaky handling with a `NoneType .sku` error | the rc1 deploy regression |

```bash
./faultctl list
./faultctl inject slow-query
./faultctl clear all
```

Fault state is process-local (a restart clears everything).
