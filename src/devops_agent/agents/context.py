from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from devops_agent.agents.tool_loop import ToolLoop
from devops_agent.domain.models import AgentSpace, Investigation
from devops_agent.persistence.protocol import Store


@dataclass
class InvestigationContext:
    """Shared mutable context for the investigation Template Method / Commands."""

    store: Store
    investigation: Investigation
    space: AgentSpace | None
    brief: str
    loop: ToolLoop
    triage_text: str = ""
    investigation_text: str = ""
    mitigation_text: str = ""
    prevention_text: str = ""
    extras: dict[str, Any] = field(default_factory=dict)

    @property
    def inv(self) -> Investigation:
        return self.investigation
