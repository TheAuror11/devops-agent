# AWS DevOps Agent → this replica

This project is an in-house, deployable approximation of AWS DevOps Agent (GA 2026), not a wrapper around `aidevops.amazonaws.com`.

| AWS DevOps Agent | This repository |
|------------------|-----------------|
| Agent Spaces (on-call boundary, IAM, integrations) | `AgentSpace` + `/v1/agent-spaces` |
| Topology graph (CFn, tags, App Signals, CI/CD) | `TopologyNode` / `TopologyEdge`, `walk_topology` tool, seeded retail graph |
| Triage / Investigation / Mitigation / Prevention | `InvestigationOrchestrator` phases |
| Multi-hypothesis + counter-evidence | Local reasoner + Bedrock Converse tool loop; journal `hypothesis` records |
| Investigation journal | `GET /v1/investigations/{id}/journal` |
| Operator web app + steer chat | `apps/web` + `/chat` |
| Skills | `POST /v1/agent-spaces/{id}/skills` |
| Runbooks | RAG index + `retrieve_runbooks` |
| BYO MCP (HTTPS, read-only, allowlists) | `McpRegistry` + demo APM server |
| Webhooks (CloudWatch, PagerDuty, ServiceNow-like) | `POST /v1/webhooks/{source}` |
| Mitigation recommend-only | `MitigationPlan.execute = False`; no mutating AWS tools |
| Bedrock AgentCore (managed) | Direct `bedrock-runtime.converse` tool use on Fargate workers |
| Managed scale | SQS + ECS Fargate autoscaling, idempotent handlers, circuit breakers |
| Cross-account assume-role | Task role `sts:AssumeRole`; space `iam_role_arn` |

Intentionally **not** cloned: AWS Support-case one-click, IAM Identity Center operator app, EKS Access Entries wizard, Neptune-backed enterprise topology. Those are called out as extension points in `docs/OPERATIONS.md`.
