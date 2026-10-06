# Security

## Threat model

The LLM is **untrusted**. Prompt injection via logs, tickets, or MCP payloads must not yield infrastructure writes or secret exfiltration.

## Controls

1. **Read-only tool surface** — built-in tools wrap describe/get/list/filter only. No `Update*`, `Delete*`, `Put*`, `Invoke` except Bedrock itself.  
2. **Mitigation never executes** — `MitigationPlan.execute` is literally `False`. Plans are journal records.  
3. **MCP** — HTTPS in prod; per-space allowlists; write-verb names rejected when `read_only`.  
4. **Agent Space IAM** — workers assume the space role; do not attach AdministratorAccess. Separate prod/dev spaces.  
5. **Secrets** — third-party tokens in Secrets Manager / task secrets, never in topology attributes or journal payloads.  
6. **Idempotency + audit** — every tool call is journaled; duplicate SQS deliveries cannot double-apply (there is nothing to apply).  
7. **Result clipping** — tool JSON truncated to 12k chars before returning to the model.  
8. **Auth** — API keys locally; replace with IAM Identity Center / JWT at the ALB in production (`JWT_SECRET` must not stay at the example value).  
9. **Network** — workers in private subnets; MCP egress explicit; no public SSH.  
10. **PII / logs** — investigation descriptions may contain customer data; DynamoDB PITR + encrypted SQS; set log retention.

## What this replica does not do

It does not impersonate AWS's `aidevops.amazonaws.com` service principal. Cross-account roles you create should trust **your** worker task role, not a fake AWS service name.
