# API

Base URL: `http://localhost:8080` (local) or the ALB DNS (prod).

Auth: header `X-API-Key` (local default `dev-local-key`; optional in `APP_ENV=local`). Production should replace this with IAM / JWT (`JWT_SECRET`).

All timestamps are ISO-8601 UTC.

## Health

`GET /healthz` — liveness  
`GET /v1/health` — env, store, queue, circuit snapshot  
`GET /metrics` — Prometheus

## Agent Spaces

`GET /v1/agent-spaces`  
`POST /v1/agent-spaces` `{ name, description, accounts, regions, slack_channel, mcp_server_ids }`  
`GET /v1/agent-spaces/{id}`  
`GET /v1/agent-spaces/{id}/topology`  
`GET /v1/agent-spaces/{id}/skills`  
`POST /v1/agent-spaces/{id}/skills` `{ name, description, body, targets }`

## Investigations (async)

`POST /v1/investigations` → **202**

```json
{
  "agent_space_id": "as_retail_checkout",
  "title": "Checkout p95 latency cliff",
  "description": "Orders timing out",
  "priority": "HIGH",
  "starting_point": "Latest alarm",
  "idempotency_key": "optional-client-key"
}
```

Poll `GET /v1/investigations/{id}` until `status` is `COMPLETED` or `FAILED`.

Journal (use `after_id` to tail):

`GET /v1/investigations/{id}/journal?after_id=`

Steer:

`POST /v1/investigations/{id}/chat` `{ "content": "focus on Orders table" }`  
`GET /v1/investigations/{id}/chat`

`POST /v1/investigations/{id}/cancel`

Statuses: `QUEUED → TRIAGE → INVESTIGATING → MITIGATING → PREVENTION → COMPLETED` (`FAILED` / `CANCELLED`).

## Webhooks

`POST /v1/webhooks/{source}` with JSON body.

| source | mapping |
|--------|---------|
| `cloudwatch` | `AlarmName` / `NewStateReason` |
| `pagerduty` | incident title / body |
| other | `title` + `description` |

Idempotent on `alarmName` / `incident_key` / `id`.

## Runbooks, MCP, prevention

`GET|POST /v1/runbooks`  
`GET|POST /v1/mcp/servers` — prod requires `https://` endpoints  
`GET /v1/recommendations`  
`PATCH /v1/recommendations/{id}` `{ "status": "accepted" }`

## OpenAPI

Swagger UI: `http://localhost:8080/docs`
