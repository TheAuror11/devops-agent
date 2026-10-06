from __future__ import annotations

from typing import Any, Protocol

from devops_agent.agents.local_reasoner import execute_named_tool
from devops_agent.config import settings
from devops_agent.mcp.registry import McpRegistry, RegisteredTool
from devops_agent.observability import get_logger
from devops_agent.resilience.circuit_breaker import CircuitOpenError
from devops_agent.tools.builtin import ToolSpec, invoke_tool

log = get_logger("tool_loop")

MAX_RESULT_CHARS = 12_000


class Reasoner(Protocol):
    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


def get_reasoner() -> Reasoner:
    if settings.use_bedrock:
        from devops_agent.agents.bedrock_client import BedrockConverse

        return BedrockConverse()
    from devops_agent.agents.local_reasoner import LocalReasoner

    return LocalReasoner()


class ToolLoop:
    def __init__(
        self,
        specs: list[ToolSpec],
        mcp_tools: list[RegisteredTool] | None = None,
        mcp_registry: McpRegistry | None = None,
        mcp_server_ids: list[str] | None = None,
        on_event: Any | None = None,
    ) -> None:
        self.specs = specs
        self.mcp_tools = mcp_tools or []
        self.mcp_registry = mcp_registry
        self.mcp_server_ids = mcp_server_ids or []
        self.on_event = on_event
        self.reasoner = get_reasoner()

    def bedrock_tools(self) -> list[dict[str, Any]]:
        tools = [s.bedrock_spec() for s in self.specs]
        for t in self.mcp_tools:
            tools.append(
                {
                    "toolSpec": {
                        "name": t.bedrock_name,
                        "description": f"[MCP:{t.server_name}] {t.description}",
                        "inputSchema": {"json": t.input_schema or {"type": "object"}},
                    }
                }
            )
        return tools

    def run(self, system: str, user: str, max_rounds: int | None = None) -> str:
        max_rounds = max_rounds or settings.bedrock_max_tool_rounds
        messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": user}]}]
        tools = self.bedrock_tools()
        final = ""
        for round_idx in range(max_rounds):
            resp = self.reasoner.converse(messages, system, tools)
            msg = resp["output"]["message"]
            messages.append(msg)
            stop = resp.get("stopReason")
            text = _extract_text(msg)
            if text:
                final = text
                if self.on_event:
                    self.on_event("model_text", {"round": round_idx, "text": text[:2000]})
            if stop != "tool_use":
                return final or text
            tool_results = []
            for block in msg.get("content", []):
                if "toolUse" not in block:
                    continue
                tu = block["toolUse"]
                result = self._dispatch(tu["name"], tu.get("input") or {})
                clipped = _clip(result)
                if self.on_event:
                    self.on_event(
                        "tool_call",
                        {"name": tu["name"], "input": tu.get("input"), "result": clipped},
                    )
                tool_results.append(
                    {
                        "toolResult": {
                            "toolUseId": tu["toolUseId"],
                            "content": [{"json": clipped}],
                        }
                    }
                )
            messages.append({"role": "user", "content": tool_results})
        return final or "Investigation stopped after max tool rounds."

    def _dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        for spec in self.specs:
            if spec.name == name:
                return invoke_tool(spec, arguments)
        if name.startswith("mcp_") and self.mcp_registry:
            try:
                result = self.mcp_registry.call(name, arguments, self.mcp_server_ids)
                return result if isinstance(result, dict) else {"result": result}
            except CircuitOpenError as exc:
                return {"error": str(exc), "degraded": True}
            except Exception as exc:  # noqa: BLE001
                log.exception("mcp_tool_failed", tool=name)
                return {"error": str(exc), "degraded": True}
        return execute_named_tool(self.specs, name, arguments)


def _extract_text(message: dict[str, Any]) -> str:
    parts = [b["text"] for b in message.get("content", []) if "text" in b]
    return "\n".join(parts).strip()


def _clip(payload: dict[str, Any]) -> dict[str, Any]:
    raw = str(payload)
    if len(raw) <= MAX_RESULT_CHARS:
        return payload
    return {"truncated": True, "preview": raw[:MAX_RESULT_CHARS]}
