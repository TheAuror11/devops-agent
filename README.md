# DevOps Agent

Production-grade **AI DevOps / debugging agent for AWS** — an in-house replica of [AWS DevOps Agent](https://aws.amazon.com/devops-agent/): Agent Spaces, topology-aware multi-hypothesis investigation, RAG over runbooks, BYO MCP tool registry, operator web app, and ECS Fargate scale-out to **100+ concurrent investigations**.

Architecture is documented in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md). Feature-by-feature mapping to AWS DevOps Agent is in [`docs/COMPARISON.md`](docs/COMPARISON.md).

## What it does

When an incident arrives (webhook, CloudWatch, PagerDuty, or an operator), the agent:

1. **Triage** — correlates related alarms at machine speed  
2. **Investigation** — walks topology, pulls metrics/logs/traces/deploys, generates competing hypotheses, tests supporting *and* counter-evidence  
3. **Mitigation** — writes a rollback-aware plan (**never executes writes** on infrastructure)  
4. **Prevention** — clusters the incident into durable recommendations  

Every step is appended to an **immutable investigation journal**. Operators can steer in natural language.

```
Alert → API → SQS → ECS Fargate workers
                      ├ Bedrock Converse (tool use)
                      ├ RAG runbooks (BM25 / Titan + OpenSearch)
                      ├ Built-in AWS tools (read-only)
                      └ MCP registry (allowlisted, read-only)
```

## Quick start (local, no AWS account required)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env

# Terminal 1 — control plane (embeds the investigation worker)
make api

# Terminal 2 — operator UI
cd apps/web && npm install && npm run dev
```

Open [http://localhost:5173](http://localhost:5173). Start an investigation titled **Checkout p95 latency cliff**. Watch triage → hypotheses → root cause (DynamoDB pool / WCU) → mitigation → prevention.

The local reasoner is used when `BEDROCK_MODEL_ID` is empty. Point it at Bedrock to use real models:

```bash
export BEDROCK_MODEL_ID=anthropic.claude-sonnet-4-20250514-v1:0
export AWS_REGION=us-east-1
```

Optional demo MCP server (APM latency + SLO budget):

```bash
python -m devops_agent.mcp.demo_server   # :8090
```

## Production deploy

See [`docs/OPERATIONS.md`](docs/OPERATIONS.md). CDK lives in `infra/cdk`:

```bash
cd infra/cdk
pip install -r requirements.txt
npx cdk deploy DevOpsAgentStack -c region=us-east-1
```

Workers autoscale on SQS visible-message depth (`min 4 / max 40` tasks × `WORKER_CONCURRENCY=4` ≈ **160 in-flight investigations**).

## Layout

| Path | Role |
|------|------|
| `src/devops_agent/api` | Control plane FastAPI |
| `src/devops_agent/worker` | Idempotent SQS / local queue consumer |
| `src/devops_agent/agents` | Triage / Investigation / Mitigation / Prevention + Bedrock tool loop |
| `src/devops_agent/rag` | Runbook chunking + BM25 (OpenSearch hook) |
| `src/devops_agent/mcp` | MCP JSON-RPC client, registry, demo server |
| `src/devops_agent/resilience` | Circuit breakers, idempotency locks |
| `apps/web` | Operator console (investigations, journal, topology, MCP, prevention) |
| `runbooks/` | Seed operational playbooks for RAG |
| `infra/cdk` | VPC, ALB, ECS Fargate, SQS+DLQ, DynamoDB, autoscaling, IAM |
| `docs/` | Architecture, API, security, operations |

## Tests

```bash
make test
```

## License

Apache-2.0
