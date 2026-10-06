# DynamoDB throttling and client connection pool saturation

Use this runbook when checkout or order-write paths show latency cliffs, `ProvisionedThroughputExceededException`, or logs that mention DynamoDB connection pool waiters.

## Signals

- CloudWatch `ThrottledRequests` or `UserErrors` on the table
- Application logs: `Unable to acquire DynamoDB connection from pool`
- X-Ray / traces with `pool_wait_ms` far above the request timeout budget
- Consumed WCU / provisioned WCU > 1.0 for several minutes

## Hypotheses to test in parallel

1. **Capacity** — provisioned WCU/RCU too low for the current write shape (especially after a batch-write deploy).
2. **Client pool** — pool size too small *or* too large (amplifies throttling). Waiters > 0 with active ~= max is saturation.
3. **Hot partition** — a single pk absorbing writes. Check `SuccessfulRequestLatency` per key pattern.
4. **Downstream symptom** — payment or notification latency that *starts after* the DynamoDB wait is not the root cause.

## Immediate mitigation (operator executed)

1. Raise provisioned WCU (or switch the table to on-demand) before scaling the compute fleet.
2. Confirm `ThrottledRequests` returns to ~0 for five minutes.
3. If still saturated, disable batching / reduce client pool and fail fast.
4. Rollback the last write-path deploy if capacity change does not restore p95.

## Validation

- Table `ConsumedWriteCapacityUnits` < provisioned (or on-demand, no throttles)
- Checkout p95 back under SLO
- Pool waiters = 0
- Payment latency follows checkout recovery (confirm cascade)

## Rollback

Restore previous WCU if the capacity change causes cost shock without SLO recovery. Re-enable batch writes only behind a feature flag after a staging load test.

## Prevention

- Alarm when consumed / provisioned WCU > 0.7 for 3 minutes
- Export pool active/idle/waiters as custom metrics
- Load-test batch-write paths with production-like item sizes
