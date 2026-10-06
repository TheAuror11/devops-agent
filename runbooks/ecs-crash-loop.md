# ECS task crash loop and CPU throttling

## Signals

- ECS `RunningTaskCount` flapping vs desired
- Container Insights CPU throttled time
- Sidecar + main container sharing *per-container* limits (not pod/task totals)

## Hypotheses

1. Memory limit too low (OOMKilled)
2. Sidecar consuming the task CPU/memory budget
3. Health check too aggressive after a slow dependency
4. Image pull / task IAM failures (does not look like app 5xx)

Always inspect task definition resource limits per container, not just service-level CPU.
