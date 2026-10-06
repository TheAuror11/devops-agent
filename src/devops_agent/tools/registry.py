from __future__ import annotations

from collections.abc import Callable
from typing import Any

from devops_agent.agents.reasoner import Reasoner, get_reasoner
from devops_agent.agents.tool_loop import ToolLoop
from devops_agent.mcp.registry import McpRegistry, RegisteredTool
from devops_agent.tools.builtin import ToolSpec, builtin_tools, invoke_tool
from devops_agent.topology.context import agent_space_id_var


class ToolRegistry:
    """Unified name → ToolSpec / MCP dispatch map (Factory product)."""

    def __init__(
        self,
        specs: list[ToolSpec],
        mcp_tools: list[RegisteredTool] | None = None,
        mcp_registry: McpRegistry | None = None,
        mcp_server_ids: list[str] | None = None,
    ) -> None:
        self.specs = {s.name: s for s in specs}
        self.mcp_tools = {t.bedrock_name: t for t in (mcp_tools or [])}
        self.mcp_registry = mcp_registry
        self.mcp_server_ids = mcp_server_ids or []

    def bedrock_tools(self) -> list[dict[str, Any]]:
        tools = [s.bedrock_spec() for s in self.specs.values()]
        for t in self.mcp_tools.values():
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

    def dispatch(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        spec = self.specs.get(name)
        if spec:
            return invoke_tool(spec, arguments)
        if name in self.mcp_tools and self.mcp_registry:
            from devops_agent.resilience.circuit_breaker import CircuitOpenError

            try:
                result = self.mcp_registry.call(name, arguments, self.mcp_server_ids)
                return result if isinstance(result, dict) else {"result": result}
            except CircuitOpenError as exc:
                return {"error": str(exc), "degraded": True}
            except Exception as exc:  # noqa: BLE001
                return {"error": str(exc), "degraded": True}
        return {"error": f"unknown tool {name}"}


class ToolRegistryFactory:
    """Factory: compose builtin tools + MCP allowlist into a ToolLoop."""

    def __init__(self, mcp: McpRegistry | None = None, reasoner: Reasoner | None = None) -> None:
        self.mcp = mcp
        self.reasoner = reasoner

    def build_registry(
        self,
        agent_space_id: str,
        mcp_server_ids: list[str] | None = None,
        include_mcp: bool = True,
    ) -> ToolRegistry:
        mcp_tools: list[RegisteredTool] = []
        if include_mcp and self.mcp and mcp_server_ids:
            mcp_tools = self.mcp.tools_for_space(mcp_server_ids)
        return ToolRegistry(
            specs=builtin_tools(agent_space_id=agent_space_id or None),
            mcp_tools=mcp_tools,
            mcp_registry=self.mcp,
            mcp_server_ids=mcp_server_ids or [],
        )

    def build_loop(
        self,
        agent_space_id: str,
        mcp_server_ids: list[str] | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
        include_mcp: bool = True,
    ) -> ToolLoop:
        if agent_space_id:
            agent_space_id_var.set(agent_space_id)
        registry = self.build_registry(agent_space_id, mcp_server_ids, include_mcp=include_mcp)
        return ToolLoop(
            registry=registry,
            reasoner=self.reasoner or get_reasoner(),
            on_event=on_event,
        )
