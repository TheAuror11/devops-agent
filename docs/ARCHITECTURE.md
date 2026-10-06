# Architecture

**Status:** authored for production; reviewed as the in-house equivalent of AWS DevOps Agent (Agent Spaces, topology graph, investigation journal, MCP, mitigation-is-recommend-only).

**Goal:** cut incident MTTR ~70% vs dashboard-hopping by running structured, multi-hypothesis RCA with architectural context, and scale to **100+ concurrent investigations**.

## Why this shape

AWS DevOps Agent is not a chat wrapper around an LLM. It is a **lifecycle of specialized capabilities** that share a topology graph and an audit journal, running inside an **Agent Space** (the on-call boundary). This system copies that decomposition and implements the scale path AWS hides behind a managed control plane: **SQS + ECS Fargate + idempotent handlers + per-provider circuit breakers**.

```
                    ┌──────────────────────────────────────────┐
                    │         Operator web app / API           │
                    │  Agent Spaces · Investigations · Chat    │
                    │  Topology · Skills · MCP · Prevention    │
                    └───────────────┬──────────────────────────┘
                                    │ HTTPS + API key / IAM
                    ┌───────────────▼──────────────────────────┐
                    │     Control plane (FastAPI on Fargate)   │
                    │  auth, CRUD, webhooks, enqueue, metrics  │
                    └───────┬───────────────────┬──────────────┘
                            │                   │
                   DynamoDB + S3         SQS investigations
                   OpenSearch RAG               │
                                                ▼
                    ┌──────────────────────────────────────────┐
                    │  Data plane workers (ECS Fargate)        │
                    │  claim idempotency lock → orchestrate    │
                    │  Triage → Investigation → Mitigation     │
                    │  → Prevention                            │
                    │  Bedrock Converse tool loop              │
                    │  AWS read APIs · MCP · retrieve_runbooks │
                    └──────────────────────────────────────────┘
```

## Agent Space

An Agent Space is the **operational perimeter**: AWS accounts, regions, capability providers, MCP server IDs, IAM role to assume, Slack channel, skills, runbooks, topology, and investigation history. Spaces are isolated — a checkout on-call space must not see payroll topology.

Scope Agent Spaces the way you assign pagers: one per on-call rotation, split prod vs non-prod, never share IAM roles across environments.

## Topology graph

Before investigation, the agent needs a living map, not a CMDB dump:

| Discovery | What it adds |
|-----------|----------------|
| CloudFormation / CDK | Static stack relationships |
| Resource Explorer tags | `app` / `env` / `team` grouping |
| CloudWatch Application Signals / APM (MCP) | Runtime call edges |
| GitHub / CodePipeline | Deploy lineage back to SHA |

Investigation **walks edges** from the symptomatic node. Mitigation **checks blast radius** on the same graph. Without it the model searches telemetry blindly.

Seeded demo graph: `checkout-alb → checkout-api → Orders (DynamoDB)` and `checkout-api → payments-api`, plus alarms, log groups, and `checkout-cd`.

## Investigation lifecycle

Mirrors AWS DevOps Agent capabilities:

1. **Triage** — high volume, short duration. Correlate alarms that share an event (checkout p95 + error rate + *later* payments latency). Operators can unlink.
2. **Investigation** — acquire context (affected + changed), collect evidence vs baseline, generate **≥3 competing hypotheses**, validate supporting *and* counter-evidence, classify ROOT_CAUSE / CAUSE / REFUTED.
3. **Mitigation** — strategy, steps, validation, success criteria, rollback, blast radius. **Write APIs are not exposed to the model.** Execution stays with the operator.
4. **Prevention** — cluster this incident into observability, capacity, resilience, pipeline, and governance recommendations.

The **journal** is the immutable timeline (tool calls, hypotheses, operator steers). Chat is a first-class steer, not a side channel.

## Bedrock tool-calling

Workers call `bedrock-runtime.converse` with `toolConfig.tools[]` (`toolSpec` + JSON Schema). Loop:

```
messages += assistant(toolUse*)
execute tools with circuit breaker + size clip
messages += user(toolResult*)
until stopReason == end_turn or max rounds
```

When `BEDROCK_MODEL_ID` is unset, `LocalReasoner` implements the same protocol so local/dev/CI exercise the full lifecycle without model spend.

Built-in tools (all read-only): `list_alarms`, `get_metrics`, `query_logs`, `get_traces`, `lookup_cloudtrail`, `list_deployments`, `describe_resource`, `walk_topology`, `retrieve_runbooks`, plus MCP tools registered for the space (`mcp_<server>_<tool>`).

## RAG over runbooks

Runbooks in `runbooks/` (and API uploads) are chunked (~900 words, 120 overlap) and indexed with **BM25**. Production path: Titan Text Embeddings v2 → OpenSearch k-NN (endpoint via `OPENSEARCH_ENDPOINT`). Skills are injected into the system prompt; runbooks are retrieved on demand so the model cites *your* playbooks, not generic advice.

## MCP tool registry

Parity with AWS DevOps Agent BYO MCP:

- Register servers at **account** level (`POST /v1/mcp/servers`)
- Enable a subset per Agent Space (`mcp_server_ids`)
- **Allowlist** tools; refuse write-like names when `read_only=true`
- HTTPS required in `APP_ENV=prod`; localhost allowed locally
- Failures trip a **per-server circuit breaker** so a down Grafana MCP does not stall RCA

Demo server: `devops_agent.mcp.demo_server` (`query_apm_latency`, `query_error_budget`).

## Scale: 100+ concurrent investigations

See [`SCALING.md`](SCALING.md) for the full system design. Summary:

| Concern | Design |
|---------|--------|
| Ingress burst | API is stateless; `POST /v1/investigations` returns 202 and enqueues |
| Backpressure | 429 rate limit / 503 when queue depth or oldest-message age exceeds SLO |
| Queue | SQS **standard** by default (max throughput). Optional FIFO for per-space ordering |
| Poison | DLQ after 5 receives + CloudWatch alarm; worker forces visibility 0 (does not delete poison) |
| Exactly-once work | DynamoDB conditional lease `process:{id}` in prod; in-memory locally |
| Duplicate creates | API `claim("create:{idempotency_key}")` (DynamoDB-backed in prod) |
| Horizontal scale | Fargate workers `min 4 / max 40` × `ThreadPool(WORKER_CONCURRENCY)` → ~160 in-flight. Scale on depth **and** oldest age |
| Long jobs | Visibility heartbeat every 300s while orchestrator runs |
| Bulkheads | Semaphores on Bedrock and tool/MCP calls per task |
| Isolation | Per-investigation handler; circuit breakers per provider |

## Persistence

**Local:** JSON under `DATA_DIR` (MemoryStore).  
**Prod:** DynamoDB single table `devops-agent-store`:

| pk | sk | entity |
|----|----|--------|
| `SPACE` | `SPACE#{id}` | AgentSpace |
| `SPACE#{id}` | `INV#{id}` | Investigation |
| `INV` | `INV#{id}` | Investigation (global get) |
| `INV#{id}` | `JRNL#{ts}#{id}` | Journal |
| `SPACE#{id}` | `NODE#{id}` / `EDGE#{id}` | Topology |
| `MCP` | `MCP#{id}` | McpServer |
| `RB` | `RB#{id}` | Runbook |

## Observability

JSON logs with `correlation_id` / `investigation_id`. Prometheus `/metrics`: investigation duration, tool calls, Bedrock stop reasons, circuit state, in-flight gauges. ECS Container Insights + deployment circuit breaker on the service itself.

## Trust boundary

The model is untrusted. Tools are the policy enforcement point: read-only AWS APIs, MCP write-verb deny, result clipping, no shell, no IAM privilege beyond the Agent Space role. See [`SECURITY.md`](SECURITY.md).
