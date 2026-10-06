from __future__ import annotations

from typing import Protocol

from devops_agent.agents.context import InvestigationContext
from devops_agent.agents.journal import InvestigationObserver
from devops_agent.agents.parsing import (
    parse_hypotheses,
    parse_mitigation,
    parse_recommendations,
    parse_root_cause,
)
from devops_agent.agents.prompts import (
    INVESTIGATION_SYSTEM,
    MITIGATION_SYSTEM,
    PREVENTION_SYSTEM,
    TRIAGE_SYSTEM,
)
from devops_agent.domain.models import InvestigationStatus, JournalRecordType, utcnow


class PhaseCommand(Protocol):
    """Command pattern: one executable investigation phase."""

    name: str
    status: InvestigationStatus

    def execute(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None: ...


class _BasePhase:
    name: str
    status: InvestigationStatus

    def _transition(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        inv = ctx.inv
        inv.status = self.status
        inv.updated_at = utcnow()
        if self.status == InvestigationStatus.TRIAGE and inv.started_at is None:
            inv.started_at = utcnow()
        ctx.store.put_investigation(inv)
        journal.on_record(JournalRecordType.STATUS_CHANGE, self.status.value)


class TriagePhase(_BasePhase):
    name = "triage"
    status = InvestigationStatus.TRIAGE

    def execute(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        self._transition(ctx, journal)
        ctx.triage_text = ctx.loop.run(TRIAGE_SYSTEM, ctx.brief)
        journal.on_record(JournalRecordType.TRIAGE_SUMMARY, "Triage complete", ctx.triage_text)
        journal.on_record(JournalRecordType.CORRELATION, "Alert correlation", ctx.triage_text)


class InvestigatePhase(_BasePhase):
    name = "investigate"
    status = InvestigationStatus.INVESTIGATING

    def execute(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        self._transition(ctx, journal)
        journal.on_record(
            JournalRecordType.CONTEXT_ACQUIRED,
            "Context acquisition",
            "Walking topology and change window.",
        )
        ctx.investigation_text = ctx.loop.run(
            INVESTIGATION_SYSTEM,
            ctx.brief + "\n\nTriage findings:\n" + ctx.triage_text,
        )
        inv = ctx.inv
        inv.hypotheses = parse_hypotheses(ctx.investigation_text)
        inv.root_cause = parse_root_cause(ctx.investigation_text)
        inv.summary = ctx.investigation_text[:4000]
        ctx.store.put_investigation(inv)
        journal.on_record(
            JournalRecordType.ROOT_CAUSE,
            "Root cause",
            inv.root_cause or ctx.investigation_text[:1500],
        )
        for hyp in inv.hypotheses:
            journal.on_record(
                JournalRecordType.HYPOTHESIS,
                hyp.title,
                hyp.statement,
                {"status": hyp.status, "confidence": hyp.confidence},
            )


class MitigatePhase(_BasePhase):
    name = "mitigate"
    status = InvestigationStatus.MITIGATING

    def execute(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        self._transition(ctx, journal)
        ctx.mitigation_text = ctx.loop.run(
            MITIGATION_SYSTEM,
            ctx.brief + "\n\nRoot cause:\n" + (ctx.inv.root_cause or ctx.investigation_text),
        )
        ctx.inv.mitigation = parse_mitigation(ctx.mitigation_text)
        ctx.store.put_investigation(ctx.inv)
        journal.on_record(JournalRecordType.MITIGATION_PLAN, "Mitigation plan", ctx.mitigation_text)


class PreventPhase(_BasePhase):
    name = "prevent"
    status = InvestigationStatus.PREVENTION

    def execute(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        self._transition(ctx, journal)
        ctx.prevention_text = ctx.loop.run(
            PREVENTION_SYSTEM,
            ctx.brief
            + "\n\nRoot cause:\n"
            + (ctx.inv.root_cause or "")
            + "\n\n"
            + ctx.investigation_text,
        )
        for rec in parse_recommendations(ctx.prevention_text, ctx.inv):
            ctx.store.put_recommendation(rec)
        journal.on_record(
            JournalRecordType.PREVENTION,
            "Prevention recommendations",
            ctx.prevention_text,
        )


def default_phase_pipeline() -> list[PhaseCommand]:
    """Factory for the standard AWS DevOps Agent-style lifecycle pipeline."""
    return [TriagePhase(), InvestigatePhase(), MitigatePhase(), PreventPhase()]
