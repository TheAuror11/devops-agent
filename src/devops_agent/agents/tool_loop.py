from __future__ import annotations

from collections.abc import Callable
from typing import Any

from devops_agent.agents.reasoner import Reasoner, get_reasoner
from devops_agent.config import settings
from devops_agent.observability import get_logger

log = get_logger("tool_loop")

MAX_RESULT_CHARS = 12_000


class ToolLoop:
    """Bedrock-shaped tool-use loop over a ToolRegistry (or legacy specs)."""

    def __init__(
        self,
        *,
        registry: Any | None = None,
        specs: list[Any] | None = None,
        mcp_tools: list[Any] | None = None,
        mcp_registry: Any | None = None,
        mcp_server_ids: list[str] | None = None,
        reasoner: Reasoner | None = None,
        on_event: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        if registry is not None:
            self.registry = registry
        else:
            # Legacy Adapter: wrap old constructor args into a ToolRegistry.
            from devops_agent.tools.registry import ToolRegistry

            self.registry = ToolRegistry(
                specs=list(specs or []),
                mcp_tools=list(mcp_tools or []),
                mcp_registry=mcp_registry,
                mcp_server_ids=mcp_server_ids or [],
            )
        self.reasoner = reasoner or get_reasoner()
        self.on_event = on_event

    def bedrock_tools(self) -> list[dict[str, Any]]:
        return self.registry.bedrock_tools()

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
                result = self.registry.dispatch(tu["name"], tu.get("input") or {})
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


def _extract_text(message: dict[str, Any]) -> str:
    parts = [b["text"] for b in message.get("content", []) if "text" in b]
    return "\n".join(parts).strip()


def _clip(payload: dict[str, Any]) -> dict[str, Any]:
    raw = str(payload)
    if len(raw) <= MAX_RESULT_CHARS:
        return payload
    return {"truncated": True, "preview": raw[:MAX_RESULT_CHARS]}
