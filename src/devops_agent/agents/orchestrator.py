from __future__ import annotations

from devops_agent.agents.parsing import (
    parse_hypotheses,
    parse_mitigation,
    parse_recommendations,
    parse_root_cause,
)
from devops_agent.agents.prompts import CHAT_SYSTEM
from devops_agent.agents.workflow import InvestigationWorkflow, build_chat_loop
from devops_agent.domain.models import ChatMessage, Investigation, JournalRecordType
from devops_agent.mcp.registry import McpRegistry
from devops_agent.persistence.protocol import Store

# Re-export parsers for backward-compatible imports / tests.
__all__ = [
    "InvestigationOrchestrator",
    "parse_hypotheses",
    "parse_mitigation",
    "parse_recommendations",
    "parse_root_cause",
]


class InvestigationOrchestrator:
    """Facade over InvestigationWorkflow (Template Method + phase Commands).

    Public API for the worker and FastAPI chat routes. Internals use:
    - Template Method — `InvestigationWorkflow`
    - Command — phase pipeline
    - Observer — `JournalEmitter`
    - Factory — `ToolRegistryFactory`
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.mcp = McpRegistry(store)
        self._workflow = InvestigationWorkflow(store, mcp=self.mcp)

    def run(self, investigation_id: str) -> Investigation:
        return self._workflow.run(investigation_id)

    def chat(self, investigation_id: str, content: str) -> ChatMessage:
        from devops_agent.agents.journal import JournalEmitter

        inv = self.store.get_investigation(investigation_id)
        if inv is None:
            raise KeyError(investigation_id)
        user_msg = ChatMessage(investigation_id=inv.id, role="user", content=content)
        self.store.put_chat(user_msg)
        journal = JournalEmitter(self.store, inv)
        journal.on_record(
            JournalRecordType.OPERATOR_STEER,
            "Operator message",
            content,
            actor="operator",
        )
        journal_rows = self.store.list_journal(inv.id)
        journal_txt = "\n".join(
            f"[{j.record_type}] {j.title}: {j.body[:400]}" for j in journal_rows[-30:]
        )
        loop = build_chat_loop()
        reply = loop.run(
            CHAT_SYSTEM,
            f"Investigation {inv.title}\nStatus {inv.status}\nRoot cause: {inv.root_cause}\n"
            f"Journal:\n{journal_txt}\n\nOperator: {content}",
            max_rounds=4,
        )
        agent_msg = ChatMessage(investigation_id=inv.id, role="agent", content=reply)
        self.store.put_chat(agent_msg)
        journal.on_record(JournalRecordType.CHAT, "Agent reply", reply)
        return agent_msg
