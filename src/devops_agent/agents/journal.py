from __future__ import annotations

from typing import Any, Protocol

from devops_agent.domain.models import Investigation, JournalRecord, JournalRecordType
from devops_agent.persistence.protocol import Store


class InvestigationObserver(Protocol):
    """Observer for investigation lifecycle and tool-loop events."""

    def on_record(
        self,
        record_type: JournalRecordType,
        title: str,
        body: str = "",
        payload: dict[str, Any] | None = None,
        actor: str = "agent",
    ) -> None: ...

    def on_event(self, kind: str, data: dict[str, Any]) -> None: ...


class JournalEmitter:
    """Observer that persists an immutable investigation journal.

    Also adapts ToolLoop's `(kind, data)` callbacks into journal records
    (tool_call → TOOL_CALL + EVIDENCE, model_text → EVIDENCE).
    """

    def __init__(self, store: Store, investigation: Investigation) -> None:
        self.store = store
        self.investigation = investigation

    def on_record(
        self,
        record_type: JournalRecordType,
        title: str,
        body: str = "",
        payload: dict[str, Any] | None = None,
        actor: str = "agent",
    ) -> None:
        self.store.append_journal(
            JournalRecord(
                investigation_id=self.investigation.id,
                execution_id=self.investigation.execution_id,
                record_type=record_type,
                title=title,
                body=body,
                payload=payload or {},
                actor=actor,
            )
        )

    def on_event(self, kind: str, data: dict[str, Any]) -> None:
        if kind == "tool_call":
            self.on_record(
                JournalRecordType.TOOL_CALL,
                f"tool:{data.get('name')}",
                body=str(data.get("result"))[:1500],
                payload=data,
            )
            self.on_record(
                JournalRecordType.EVIDENCE,
                f"evidence from {data.get('name')}",
                payload=data,
            )
        elif kind == "model_text" and data.get("text"):
            self.on_record(JournalRecordType.EVIDENCE, "reasoning", body=data["text"][:2000])


class CompositeObserver:
    """Fan-out Observer for journal + metrics (or future Slack notifiers)."""

    def __init__(self, *observers: InvestigationObserver) -> None:
        self._observers = list(observers)

    def on_record(
        self,
        record_type: JournalRecordType,
        title: str,
        body: str = "",
        payload: dict[str, Any] | None = None,
        actor: str = "agent",
    ) -> None:
        for obs in self._observers:
            obs.on_record(record_type, title, body, payload, actor)

    def on_event(self, kind: str, data: dict[str, Any]) -> None:
        for obs in self._observers:
            obs.on_event(kind, data)
