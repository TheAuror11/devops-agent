from __future__ import annotations

from typing import Any

import httpx

from devops_agent.domain.models import McpServer
from devops_agent.observability import get_logger
from devops_agent.resilience.circuit_breaker import CircuitOpenError, get_circuit_registry

log = get_logger("mcp")

WRITE_VERBS = ("put", "create", "update", "delete", "write", "patch", "post", "execute", "invoke", "apply")


class McpError(RuntimeError):
    pass


class McpClient:
    """Minimal JSON-RPC MCP client (initialize / tools/list / tools/call).

    Mirrors AWS DevOps Agent BYO MCP constraints:
    - HTTPS (or localhost in APP_ENV=local)
    - read-only tools only
    - per-space tool allowlists
    """

    def __init__(self, timeout: float = 15.0) -> None:
        self.timeout = timeout

    def _rpc(self, server: McpServer, method: str, params: dict[str, Any] | None = None) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
        headers = {"content-type": "application/json", **server.headers}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(server.endpoint, json=payload, headers=headers)
            resp.raise_for_status()
            body = resp.json()
        if "error" in body:
            raise McpError(str(body["error"]))
        return body.get("result")

    def list_tools(self, server: McpServer) -> list[dict[str, Any]]:
        provider = f"mcp:{server.id}"
        cb = get_circuit_registry()
        if not cb.allow(provider):
            raise CircuitOpenError(provider)
        try:
            result = self._rpc(server, "tools/list")
            cb.record_success(provider)
        except Exception:
            cb.record_failure(provider)
            raise
        tools = result.get("tools", result if isinstance(result, list) else [])
        return [t for t in tools if self._allowed(server, t.get("name", ""))]

    def call_tool(self, server: McpServer, name: str, arguments: dict[str, Any]) -> Any:
        if not self._allowed(server, name):
            raise McpError(f"tool '{name}' is not allowlisted on MCP server {server.name}")
        if server.read_only and self._looks_like_write(name):
            raise McpError(f"refusing write-like MCP tool '{name}' (read-only policy)")
        provider = f"mcp:{server.id}"
        cb = get_circuit_registry()
        if not cb.allow(provider):
            raise CircuitOpenError(provider)
        try:
            result = self._rpc(server, "tools/call", {"name": name, "arguments": arguments})
            cb.record_success(provider)
            return result
        except Exception:
            cb.record_failure(provider)
            raise

    def _allowed(self, server: McpServer, name: str) -> bool:
        if not server.allowed_tools:
            return True
        return name in server.allowed_tools

    def _looks_like_write(self, name: str) -> bool:
        lowered = name.lower()
        return any(v in lowered.split("_") or lowered.startswith(v) for v in WRITE_VERBS)
