# System Design for Scaling

Goal: **100+ concurrent investigations** with bounded latency, no duplicate RCA work across tasks, and graceful overload.

## Topology

```
                 ┌──────────── backpressure ────────────┐
                 │ rate limit / queue depth / age SLO   │
Webhooks / UI ──►│ API (Fargate 2–8)                    │──► DynamoDB
                 │ 202 Accepted                         │
                 └────────────────┬─────────────────────┘
                                  │ SQS (standard)
                                  ▼
                 ┌──────────────────────────────────────┐
                 │ Workers (Fargate 4–40)               │
                 │  ThreadPool × WORKER_CONCURRENCY     │
                 │  DynamoDB idempotency lease          │
                 │  Visibility heartbeat                │
                 │  Bedrock + tool bulkheads            │
                 │  Circuit breakers per provider       │
                 └───────────────┬──────────────────────┘
                                 │ failures × 5
                                 ▼
                              SQS DLQ (+ alarm)
```

## Capacity math

```
peak_concurrent ≈ worker_tasks × WORKER_CONCURRENCY
default CDK:    4–40 × 4 = 16–160 in-flight
```

Tune with Bedrock account TPM:

```
max_tasks ≈ floor(Bedrock_TPM / (tokens_per_investigation / duration_minutes))
```

## Patterns implemented

| Concern | Mechanism | Code / infra |
|---------|-----------|--------------|
| Decouple ingress | Async 202 + SQS | `api/routes.py`, `queueing.py` |
| Horizontal scale | ECS Fargate + step scaling on depth & age | `infra/cdk/stack.py` |
| True parallelism | `ThreadPoolExecutor(worker_concurrency)` | `worker/main.py` |
| Exactly-once work | DynamoDB conditional lease (`IDEM#…`) | `resilience/idempotency.py` |
| Long jobs | Visibility heartbeat every 300s | `worker/heartbeat.py` |
| Poison messages | MaxReceiveCount → DLQ (visibility 0) | worker + CDK DLQ |
| Overload | 429 rate limit, 503 queue pressure | `scaling/backpressure.py` |
| Blast isolation | Bedrock / tool semaphores | `scaling/bulkhead.py` |
| Provider failure | Circuit breakers | `resilience/circuit_breaker.py` |
| Readiness | `/readyz` store+queue | `api/app.py` |
| Ops signals | DLQ + oldest-age CloudWatch alarms | CDK SNS topic |

## Ingress backpressure

Before enqueue:

1. Token bucket: `MAX_INVESTIGATIONS_PER_MINUTE` per Agent Space → **429**  
2. Queue depth ≥ `MAX_QUEUE_DEPTH` → **503** + `Retry-After`  
3. Oldest message age ≥ `MAX_QUEUE_AGE_SECONDS` → **503**

Clients should retry with jitter. Webhooks share the same path.

## Idempotency leases

| Key | When |
|-----|------|
| `create:{client_key}` | API create — dedupe retries |
| `process:{investigation_id}` | Worker — one task owns the RCA |

In `APP_ENV=prod` + `STORE_BACKEND=dynamodb`, leases are **DynamoDB-backed** so two Fargate tasks cannot both run the same investigation.

## FIFO vs standard

Default deploy uses a **standard** queue for max throughput (100+ concurrent).  
FIFO (`SQS_IS_FIFO=true`, `.fifo` URL) adds per–`agent_space_id` ordering at the cost of throughput — enable only if strict per-space serialisation is required. FIFO-only send fields are never attached to standard queues.

## Failure modes

| Symptom | Action |
|---------|--------|
| Investigations stuck QUEUED | Worker desired count, SQS depth, IAM |
| Duplicate RCA | Confirm Dynamo idempotency in prod |
| Bedrock throttles | Raise `BEDROCK_MAX_RETRIES`, lower `BEDROCK_MAX_INFLIGHT_PER_TASK`, scale tasks |
| 503 on create | Workers lagging — wait for age/depth autoscaling |
| DLQ alarm | Inspect poison body; fix tool/Bedrock; redrive |

## Local vs prod

| | Local | Prod |
|--|-------|------|
| Queue | In-memory | SQS |
| Idempotency | Process memory | DynamoDB |
| Workers | Embedded thread pool | ECS 4–40 |
| Backpressure | Enabled (raise limits if testing bursts) | Enabled |
