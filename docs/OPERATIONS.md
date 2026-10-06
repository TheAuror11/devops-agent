# Operations

## Local

```bash
make install
cp .env.example .env
make api          # :8080 control plane + embedded worker
cd apps/web && npm install && npm run dev   # :5173
```

Seeded Agent Space: `as_retail_checkout` (`retail-checkout-prod`).

Docker:

```bash
docker compose up --build
# API :8080  UI :80  MCP :8090
```

## Production (ECS Fargate)

1. Create Bedrock model access in `us-east-1` (or your inference region).  
2. `cd infra/cdk && npx cdk bootstrap && npx cdk deploy -c region=us-east-1`  
3. Set `BEDROCK_MODEL_ID` and `API_KEYS` as task environment / SSM.  
4. Optionally set `OPENSEARCH_ENDPOINT` and create index `devops-agent-runbooks`.  
5. Cross-account: Agent Space `iam_role_arn` in each workload account with trust to the worker task role; least-privilege describe/get/list as in AWS DevOps Agent.  
6. Point CloudWatch / PagerDuty webhooks at `https://<alb>/v1/webhooks/cloudwatch`.

### Worker capacity math

- Investigation duration ≈ 5–8 minutes with Bedrock, ~seconds with the local reasoner.  
- SQS visibility timeout = 15 minutes.  
- `desired worker tasks × WORKER_CONCURRENCY` ≥ peak concurrent investigations.  
- Default CDK: 4–40 tasks × 4 = **16–160** concurrent. Scale `max_capacity` for larger fleets.

### Failure modes

| Symptom | Check |
|---------|--------|
| Investigations stuck `QUEUED` | Worker logs, SQS depth, IAM `sqs:ReceiveMessage` |
| `FAILED` with Bedrock AccessDenied | Model access + `bedrock:InvokeModel` on task role |
| Empty MCP evidence | Circuit snapshot on `/v1/health`; HTTPS reachability |
| Duplicate investigations | Client must send `idempotency_key`; webhooks already key on alarm id |
| DLQ growth | Read poison body; 5 receives then DLQ |

### Runbooks

Drop Markdown in `runbooks/` or `POST /v1/runbooks`. Rebuild is automatic on API create; workers refresh via store list on retrieve.

### Slack / tickets

Mitigation remains recommend-only. Wire Slack by implementing a notifier on journal `status_change` (out of box: `slack_channel` stored on the space). Do not grant the model `chat.postMessage` write via MCP unless allowlisted and reviewed.

### Metrics to page on

- `devops_agent_investigations_started_total` vs completed  
- `devops_agent_investigation_duration_seconds` p95  
- `devops_agent_circuit_open`  
- SQS `ApproximateAgeOfOldestMessage`  
- Worker CPU / Bedrock throttles
