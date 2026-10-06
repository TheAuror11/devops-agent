# Deployment correlation

Every investigation must answer: **what changed in the blast radius window?**

1. List CI/CD deployments (GitHub Actions, GitLab, CodePipeline) T-6h to T+now
2. List CloudTrail `Update*` / `Put*` / `Delete*` on affected ARNs
3. Compare deploy timestamp to metric inflection — deploy after onset is not causal
4. Treat config-only changes (log level, tags) as *refutable* unless they alter request path

If the leading hypothesis is a deploy, name the SHA, pipeline, and the exact resource it rolled.
