from __future__ import annotations

from collections.abc import Callable
from typing import Any

from devops_agent.config import settings
from devops_agent.demo.telemetry import telemetry
from devops_agent.observability import TOOL_CALLS, TOOL_LATENCY, get_logger
from devops_agent.resilience.circuit_breaker import CircuitOpenError, get_circuit_registry

log = get_logger("tools")

ToolHandler = Callable[[dict[str, Any]], dict[str, Any]]


class ToolSpec:
    def __init__(
        self,
        name: str,
        description: str,
        schema: dict[str, Any],
        handler: ToolHandler,
        provider: str,
        read_only: bool = True,
    ) -> None:
        self.name = name
        self.description = description
        self.schema = schema
        self.handler = handler
        self.provider = provider
        self.read_only = read_only

    def bedrock_spec(self) -> dict[str, Any]:
        return {
            "toolSpec": {
                "name": self.name,
                "description": self.description,
                "inputSchema": {"json": self.schema},
            }
        }


def _ok(provider: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    get_circuit_registry().record_success(provider)
    TOOL_CALLS.labels(tool=name, status="ok").inc()
    return payload


def _err(provider: str, name: str, exc: Exception) -> dict[str, Any]:
    get_circuit_registry().record_failure(provider)
    TOOL_CALLS.labels(tool=name, status="error").inc()
    return {"error": str(exc), "provider": provider, "degraded": True}


def invoke_tool(spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
    from devops_agent.scaling.bulkhead import tool_slot

    cb = get_circuit_registry()
    if not cb.allow(spec.provider):
        TOOL_CALLS.labels(tool=spec.name, status="circuit_open").inc()
        return {
            "error": f"circuit open for {spec.provider}",
            "degraded": True,
            "provider": spec.provider,
        }
    try:
        with tool_slot():
            with TOOL_LATENCY.labels(tool=spec.name).time():
                try:
                    result = spec.handler(arguments or {})
                    log.info("tool_ok", tool=spec.name, provider=spec.provider)
                    return _ok(spec.provider, spec.name, result)
                except CircuitOpenError as exc:
                    return {"error": str(exc), "degraded": True, "provider": spec.provider}
                except Exception as exc:  # noqa: BLE001 — tools must never crash the agent loop
                    log.exception("tool_failed", tool=spec.name)
                    return _err(spec.provider, spec.name, exc)
    except TimeoutError:
        TOOL_CALLS.labels(tool=spec.name, status="bulkhead").inc()
        return {"error": "tool bulkhead saturated", "degraded": True, "provider": spec.provider}


def builtin_tools(agent_space_id: str | None = None) -> list[ToolSpec]:
    """Factory for the read-only AWS / RAG / topology tool surface.

    `agent_space_id` is bound into topology walks (Adapter) so investigations
    stay scoped to their Agent Space.
    """
    space_id = agent_space_id

    def walk_handler(args: dict[str, Any]) -> dict[str, Any]:
        from devops_agent.topology.graph import walk

        return walk(
            args.get("node_name", ""),
            int(args.get("depth", 2)),
            space_id=space_id,
        )

    def retrieve_handler(args: dict[str, Any]) -> dict[str, Any]:
        from devops_agent.rag import get_retrieval_strategy

        hits = get_retrieval_strategy().search(args.get("query", ""), k=int(args.get("k", 4)))
        return {
            "chunks": [
                {
                    "title": h.title,
                    "path": h.path,
                    "score": round(h.score, 3),
                    "text": h.text[:1200],
                    "tags": h.tags,
                }
                for h in hits
            ]
        }

    return [
        ToolSpec(
            name="list_alarms",
            description="List CloudWatch alarms and current states for the Agent Space.",
            schema={"type": "object", "properties": {"state": {"type": "string"}}, "required": []},
            handler=_list_alarms,
            provider="cloudwatch",
        ),
        ToolSpec(
            name="get_metrics",
            description="Fetch CloudWatch metrics (p50/p95/p99 or averages) for a resource.",
            schema={
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "metric_name": {"type": "string"},
                    "resource": {"type": "string"},
                },
                "required": ["metric_name"],
            },
            handler=_get_metrics,
            provider="cloudwatch",
        ),
        ToolSpec(
            name="query_logs",
            description="Filter CloudWatch Logs for a log group with an optional pattern.",
            schema={
                "type": "object",
                "properties": {
                    "log_group": {"type": "string"},
                    "filter_pattern": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "required": ["log_group"],
            },
            handler=_query_logs,
            provider="logs",
        ),
        ToolSpec(
            name="get_traces",
            description="Fetch X-Ray / Application Signals traces for a service.",
            schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
            },
            handler=_get_traces,
            provider="xray",
        ),
        ToolSpec(
            name="lookup_cloudtrail",
            description="Lookup recent CloudTrail management events for a resource.",
            schema={
                "type": "object",
                "properties": {"resource": {"type": "string"}},
                "required": [],
            },
            handler=_cloudtrail,
            provider="cloudtrail",
        ),
        ToolSpec(
            name="list_deployments",
            description="List recent CI/CD deployments (GitHub Actions / CodePipeline) for a service.",
            schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": [],
            },
            handler=_deployments,
            provider="github",
        ),
        ToolSpec(
            name="describe_resource",
            description="Describe an AWS resource (lambda, ecs, dynamodb table) — read only.",
            schema={
                "type": "object",
                "properties": {
                    "kind": {"type": "string"},
                    "name": {"type": "string"},
                },
                "required": ["kind", "name"],
            },
            handler=_describe,
            provider="config",
        ),
        ToolSpec(
            name="walk_topology",
            description="Walk the application topology graph outward from a node to map blast radius.",
            schema={
                "type": "object",
                "properties": {
                    "node_name": {"type": "string"},
                    "depth": {"type": "integer"},
                },
                "required": ["node_name"],
            },
            handler=walk_handler,
            provider="topology",
        ),
        ToolSpec(
            name="retrieve_runbooks",
            description="RAG retrieval over operational runbooks and skills. Use before proposing fixes.",
            schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer"},
                },
                "required": ["query"],
            },
            handler=retrieve_handler,
            provider="runbooks",
        ),
    ]


def _list_alarms(args: dict[str, Any]) -> dict[str, Any]:
    alarms = telemetry.alarms()
    state = (args.get("state") or "").upper()
    if state:
        alarms = [a for a in alarms if a["StateValue"] == state]
    if not settings.is_local:
        alarms = _live_alarms(state) or alarms
    return {"alarms": alarms}


def _get_metrics(args: dict[str, Any]) -> dict[str, Any]:
    return telemetry.metrics(
        args.get("metric_name", "Latency"),
        args.get("namespace", ""),
        args.get("resource", ""),
    )


def _query_logs(args: dict[str, Any]) -> dict[str, Any]:
    events = telemetry.logs(args.get("log_group", ""), args.get("filter_pattern", ""), int(args.get("limit", 20)))
    return {"events": events}


def _get_traces(args: dict[str, Any]) -> dict[str, Any]:
    return {"traces": telemetry.traces(args.get("service", "checkout"))}


def _cloudtrail(args: dict[str, Any]) -> dict[str, Any]:
    return {"events": telemetry.cloudtrail(args.get("resource", ""))}


def _deployments(args: dict[str, Any]) -> dict[str, Any]:
    return {"deployments": telemetry.deployments(args.get("service", ""))}


def _describe(args: dict[str, Any]) -> dict[str, Any]:
    return telemetry.describe_resource(args.get("kind", ""), args.get("name", ""))


def _live_alarms(state: str) -> list[dict[str, Any]] | None:
    try:
        import boto3

        client = boto3.client("cloudwatch", region_name=settings.aws_region)
        kwargs: dict[str, Any] = {"MaxRecords": 50}
        if state:
            kwargs["StateValue"] = state
        resp = client.describe_alarms(**kwargs)
        return [
            {
                "AlarmName": a["AlarmName"],
                "StateValue": a["StateValue"],
                "MetricName": (a.get("MetricName") or ""),
                "Namespace": a.get("Namespace", ""),
                "Reason": a.get("StateReason", ""),
            }
            for a in resp.get("MetricAlarms", [])
        ]
    except Exception:
        return None
