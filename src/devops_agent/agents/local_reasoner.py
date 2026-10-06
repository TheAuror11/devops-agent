from __future__ import annotations

from typing import Any

from devops_agent.observability import get_logger
from devops_agent.tools.builtin import ToolSpec, invoke_tool

log = get_logger("local_reasoner")


class LocalReasoner:
    """Deterministic multi-step reasoner used when Bedrock is not configured.

    It speaks the same Converse-shaped protocol as BedrockConverse so the
    tool loop stays identical in local, test, and prod.
    """

    def __init__(self) -> None:
        self.phase = "investigation"
        self._round = 0

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        text = _last_user_text(messages)
        tool_results = _collect_tool_results(messages)
        if "triage capability" in system.lower():
            return self._triage(tool_results)
        if "mitigation capability" in system.lower():
            return self._mitigation()
        if "prevention capability" in system.lower():
            return self._prevention()
        if "on-demand sre" in system.lower():
            return _text_response(_chat_reply(text))

        self._round += 1
        planned = self._next_tools(tool_results)
        if planned:
            return _tool_use(planned)
        return _text_response(self._conclude(tool_results))

    def _triage(self, tool_results: dict[str, Any]) -> dict[str, Any]:
        if "list_alarms" not in tool_results:
            return _tool_use(
                [
                    ("list_alarms", {"state": "ALARM"}),
                    ("walk_topology", {"node_name": "checkout-api", "depth": 2}),
                ]
            )
        return _text_response(
            "TRIAGE: Correlated checkout-p95-latency, checkout-error-rate, and payments-latency "
            "(payments fired 5 minutes later — likely the same event). Origin: checkout-api. "
            "Window: last 20 minutes. Catalog CPU is OK and should not share this investigation. "
            "Recommend a single HIGH investigation on checkout / orders."
        )

    def _next_tools(self, results: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
        wanted = [
            ("list_alarms", {"state": "ALARM"}),
            ("walk_topology", {"node_name": "checkout-api", "depth": 2}),
            ("get_metrics", {"namespace": "Checkout", "metric_name": "Latency", "resource": "checkout-api"}),
            ("query_logs", {"log_group": "/ecs/checkout-api", "filter_pattern": "ERROR", "limit": 20}),
            ("get_traces", {"service": "checkout-api"}),
            ("lookup_cloudtrail", {"resource": "checkout-api"}),
            ("list_deployments", {"service": "checkout-api"}),
            ("describe_resource", {"kind": "dynamodb", "name": "Orders"}),
            ("retrieve_runbooks", {"query": "DynamoDB throttling connection pool checkout latency", "k": 4}),
        ]
        called = set(results.keys())
        remaining = [(n, a) for n, a in wanted if n not in called]
        return remaining[:3]

    def _conclude(self, results: dict[str, Any]) -> str:
        return (
            "Investigated checkout latency with three competing hypotheses.\n\n"
            "H1 Config change (LOG_LEVEL=DEBUG 22m ago): CloudTrail shows logging verbosity only. "
            "Cannot explain a 15x p95 cliff. REFUTED.\n"
            "H2 Payment gateway slowness: payments p95 rose 5 minutes AFTER checkout onset and traces "
            "show payment TTFB starting after a 6s pool wait. Symptom, not cause. REFUTED as root.\n"
            "H3 DynamoDB Orders connection pool / WCU saturation: logs show 47/50 pool active with 23 "
            "waiters; traces annotate pool_wait_ms=6100; table consumed WCU 1380 vs provisioned 800; "
            "deploy 9f3c1a2 (batch writes + pool 20→50) landed 66 minutes before onset. Nothing contradicts. "
            "ROOT CAUSE.\n\n"
            "ROOT_CAUSE: Checkout ECS tasks cannot acquire DynamoDB connections because the Orders table is "
            "throttling under provisioned WCU=800 while consumed write capacity is ~1380, saturating the "
            "client pool (50) after the batch-write deploy. Timeouts cascade into payment-latency alarms.\n\n"
            "HYPOTHESES:\n"
            "- DynamoDB pool/WCU saturation | ROOT_CAUSE | 0.91 | pool wait + throttles + deploy correlation\n"
            "- Payment gateway degradation | CAUSE | 0.35 | contributing symptom after onset\n"
            "- Debug logging config change | REFUTED | 0.08 | cannot affect request latency\n"
        )

    def _mitigation(self) -> dict[str, Any]:
        return _text_response(
            "Strategy: restore write headroom on Orders and shed pool wait, then harden the client.\n\n"
            "Steps:\n"
            "1. Raise Orders WCU from 800 to 2000 (or switch to on-demand) as an emergency capacity change.\n"
            "2. Scale checkout-api tasks 6 → 8 only AFTER table capacity is raised (avoid amplifying throttles).\n"
            "3. Disable batch-write grouping introduced in 9f3c1a2 if throttles persist (feature flag).\n"
            "4. Drop LOG_LEVEL back to INFO after service restoration (unrelated but noisy).\n\n"
            "Validation checks: DescribeTable WCU >= 2000; CloudWatch UserErrors/Throttles == 0 for 5 min; "
            "checkout p95 < 500ms; pool waiters == 0 in logs.\n"
            "Success criteria: checkout-p95-latency OK, error rate < 1%, payment latency returns to baseline.\n"
            "Rollback: restore WCU=800 if cost spike with no latency benefit; re-enable batch writes via flag.\n"
            "Blast radius: Orders table (checkout, reporting jobs). Payments is downstream symptom only.\n"
            "Agent will not execute these writes — operator approval required."
        )

    def _prevention(self) -> dict[str, Any]:
        return _text_response(
            "RECOMMENDATIONS:\n"
            "1 | observability | Add DynamoDB ThrottledRequests and client pool wait gauges to checkout dashboards | medium | high\n"
            "2 | capacity | Autoscale Orders WCU or migrate to on-demand billing | medium | high\n"
            "3 | resilience | Bounded connection pool with fail-fast + jittered retry; circuit breaker around DynamoDB | medium | high\n"
            "4 | pipeline | Load test batch-write path in staging with production-like item sizes before merge | high | high\n"
            "5 | governance | Alarm on consumed WCU / provisioned WCU > 0.7 for 3 minutes | low | high\n"
        )


def _last_user_text(messages: list[dict[str, Any]]) -> str:
    for msg in reversed(messages):
        if msg.get("role") != "user":
            continue
        parts = []
        for block in msg.get("content", []):
            if "text" in block:
                parts.append(block["text"])
        if parts:
            return "\n".join(parts)
    return ""


def _collect_tool_results(messages: list[dict[str, Any]]) -> dict[str, Any]:
    names: dict[str, str] = {}
    results: dict[str, Any] = {}
    for msg in messages:
        for block in msg.get("content", []):
            if "toolUse" in block:
                tu = block["toolUse"]
                names[tu["toolUseId"]] = tu["name"]
            if "toolResult" in block:
                tr = block["toolResult"]
                name = names.get(tr.get("toolUseId"), "unknown")
                payload = tr.get("content", [{}])[0]
                results[name] = payload.get("json") or payload.get("text")
    return results


def _tool_use(calls: list[tuple[str, dict[str, Any]]]) -> dict[str, Any]:
    content = []
    for i, (name, args) in enumerate(calls):
        content.append(
            {
                "toolUse": {
                    "toolUseId": f"local_{name}_{i}",
                    "name": name,
                    "input": args,
                }
            }
        )
    return {"stopReason": "tool_use", "output": {"message": {"role": "assistant", "content": content}}}


def _text_response(text: str) -> dict[str, Any]:
    return {
        "stopReason": "end_turn",
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
    }


def _chat_reply(text: str) -> str:
    t = text.lower()
    if "log" in t:
        return (
            "I queried /ecs/checkout-api. Dominant errors are DynamoDB pool acquisition timeouts "
            "(47/50 active, 23 waiters) and ProvisionedThroughputExceededException on PutItem Orders."
        )
    if "steer" in t or "focus" in t:
        return "Acknowledged. I will weight that subsystem higher in the remaining hypothesis tests."
    return (
        "Root cause is Orders table WCU exhaustion saturating the checkout DynamoDB client pool after "
        "deploy 9f3c1a2. Payment latency is a cascading symptom. Mitigation is capacity + pool fail-fast, "
        "operator-executed."
    )


def execute_named_tool(specs: list[ToolSpec], name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    for spec in specs:
        if spec.name == name:
            return invoke_tool(spec, arguments)
    return {"error": f"unknown tool {name}"}
