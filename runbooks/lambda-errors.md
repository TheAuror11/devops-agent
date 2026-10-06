# Lambda error rate and intentional faults

Use when a Lambda error-rate alarm fires or CloudWatch `Errors` > 0 for a function in the Agent Space.

## Signals

- `AWS/Lambda` Errors, Throttles, Duration, ConcurrentExecutions
- Log group `/aws/lambda/<function>` containing stack traces
- Recent `UpdateFunctionCode` or `UpdateFunctionConfiguration` in CloudTrail
- X-Ray traces with 4xx/5xx on the function segment

## Hypotheses

1. Code defect in the latest publish (compare `$LATEST` vs alias)
2. Timeout too low vs downstream latency
3. Missing IAM permission after a policy tightening
4. Intentional test exception / chaos experiment (check tags `fault=injected`)

## Mitigation (recommend only)

- Rollback to previous published version via alias
- Increase timeout only after proving downstream is healthy
- Do not republish from console during the incident without a tracked change

## Prevention

- Require aliases + CodeDeploy canaries for production functions
- Alarm on Errors AND on duration approaching timeout (80%)
