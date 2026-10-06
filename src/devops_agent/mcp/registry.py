from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from devops_agent.domain.models import McpServer
from devops_agent.mcp.client import McpClient
from devops_agent.persistence.protocol import Store


class RegisteredTool(BaseModel):
    server_id: str
    server_name: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)
    bedrock_name: str = ""


class McpRegistry:
    """Account-level MCP registration with per-Agent-Space tool enablement."""

    def __init__(self, store: Store, client: McpClient | None = None) -> None:
        self.store = store
        self.client = client or McpClient()

    def register(self, server: McpServer) -> McpServer:
        return self.store.put_mcp(server)

    def list_servers(self) -> list[McpServer]:
        return self.store.list_mcp()

    def tools_for_space(self, mcp_server_ids: list[str]) -> list[RegisteredTool]:
        out: list[RegisteredTool] = []
        for sid in mcp_server_ids:
            server = self.store.get_mcp(sid)
            if not server or not server.enabled:
                continue
            try:
                tools = self.client.list_tools(server)
            except Exception:
                continue
            for t in tools:
                name = t.get("name", "")
                bedrock = f"mcp_{_safe(server.name)}_{_safe(name)}"[:64]
                out.append(
                    RegisteredTool(
                        server_id=server.id,
                        server_name=server.name,
                        name=name,
                        description=t.get("description", ""),
                        input_schema=t.get("inputSchema") or t.get("input_schema") or {"type": "object"},
                        bedrock_name=bedrock,
                    )
                )
        return out

    def call(self, bedrock_name: str, arguments: dict[str, Any], mcp_server_ids: list[str]) -> Any:
        for tool in self.tools_for_space(mcp_server_ids):
            if tool.bedrock_name == bedrock_name:
                server = self.store.get_mcp(tool.server_id)
                if not server:
                    raise RuntimeError("MCP server disappeared")
                return self.client.call_tool(server, tool.name, arguments)
        raise RuntimeError(f"unknown MCP tool {bedrock_name}")


def _safe(value: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in value)
