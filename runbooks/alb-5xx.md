# ALB / API Gateway 5xx spike

## Signals

- ALB `HTTPCode_Target_5XX_Count` or API Gateway `5XXError`
- Target health `UnhealthyHostCount` > 0
- Surge in target connection errors vs application 500s (different causes)

## Hypotheses

1. Target crash loop (ECS/EKS) — check deployment and OOM
2. Slow upstream causing idle timeouts (ALB 60s default vs app timeout)
3. Bad deploy shifting traffic to a broken target group
4. Dependency outage (DynamoDB, RDS, downstream HTTP)

Walk topology from the load balancer before blaming the first 5xx you see.

## Mitigation

- Shift traffic to last known-good target group
- Temporarily raise idle timeout only if traces show cutoff at exactly 60s
- Scale targets only after the dependency has headroom
