from __future__ import annotations

from typing import Any, Protocol

from devops_agent.config import settings


class Reasoner(Protocol):
    """Strategy protocol for LLM backends (Bedrock Converse vs local reasoner)."""

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]: ...


def get_reasoner() -> Reasoner:
    """Factory: select Reasoner Strategy from settings."""
    if settings.use_bedrock:
        from devops_agent.agents.bedrock_client import BedrockConverse

        return BedrockConverse()
    from devops_agent.agents.local_reasoner import LocalReasoner

    return LocalReasoner()
