from __future__ import annotations

from devops_agent.agents.context import InvestigationContext
from devops_agent.agents.journal import InvestigationObserver, JournalEmitter
from devops_agent.agents.phases import PhaseCommand, default_phase_pipeline
from devops_agent.agents.prompts import skills_block
from devops_agent.agents.tool_loop import ToolLoop
from devops_agent.domain.models import (
    Investigation,
    InvestigationStatus,
    JournalRecordType,
    utcnow,
)
from devops_agent.mcp.registry import McpRegistry
from devops_agent.observability import (
    ACTIVE_INVESTIGATIONS,
    INVESTIGATION_DURATION,
    INVESTIGATIONS_COMPLETED,
    get_logger,
    investigation_id_var,
)
from devops_agent.persistence.protocol import Store
from devops_agent.tools.registry import ToolRegistryFactory

log = get_logger("workflow")


class InvestigationWorkflow:
    """Template Method: fixed investigation lifecycle with pluggable phase Commands.

    Skeleton:
      1. load + bind context
      2. build ToolLoop (Factory) + Journal Observer
      3. run phase pipeline
      4. complete / fail
    Subclasses (or injected pipelines) can swap phase Commands without changing
    the skeleton.
    """

    def __init__(
        self,
        store: Store,
        mcp: McpRegistry | None = None,
        phases: list[PhaseCommand] | None = None,
        tool_factory: ToolRegistryFactory | None = None,
    ) -> None:
        self.store = store
        self.mcp = mcp or McpRegistry(store)
        self.phases = phases or default_phase_pipeline()
        self.tool_factory = tool_factory or ToolRegistryFactory(self.mcp)

    def run(self, investigation_id: str) -> Investigation:
        inv = self.store.get_investigation(investigation_id)
        if inv is None:
            raise KeyError(investigation_id)
        investigation_id_var.set(inv.id)
        ACTIVE_INVESTIGATIONS.inc()
        started = utcnow()
        journal: InvestigationObserver | None = None
        try:
            ctx, journal = self._prepare(inv)
            journal.on_record(
                JournalRecordType.INVESTIGATION_STARTED,
                "Investigation started",
                inv.description,
            )
            self._run_phases(ctx, journal)
            return self._complete(ctx, journal, started)
        except Exception as exc:
            self._fail(inv, exc)
            raise
        finally:
            ACTIVE_INVESTIGATIONS.dec()

    def _prepare(self, inv: Investigation) -> tuple[InvestigationContext, InvestigationObserver]:
        space = self.store.get_agent_space(inv.agent_space_id)
        skills = self.store.list_skills(inv.agent_space_id) if space else []
        skill_text = skills_block([f"### {s.name}\n{s.body}" for s in skills])
        journal: InvestigationObserver = JournalEmitter(self.store, inv)
        loop = self.tool_factory.build_loop(
            agent_space_id=inv.agent_space_id,
            mcp_server_ids=space.mcp_server_ids if space else [],
            on_event=journal.on_event,
        )
        brief = (
            f"Incident: {inv.title}\nDescription: {inv.description}\n"
            f"Starting point: {inv.starting_point}\nPriority: {inv.priority}\n"
            f"Account: {inv.account_id} Region: {inv.region}\n"
            f"Incident time: {inv.incident_time.isoformat()}\n{skill_text}"
        )
        ctx = InvestigationContext(
            store=self.store,
            investigation=inv,
            space=space,
            brief=brief,
            loop=loop,
        )
        return ctx, journal

    def _run_phases(self, ctx: InvestigationContext, journal: InvestigationObserver) -> None:
        for phase in self.phases:
            log.info("phase_start", phase=phase.name, investigation_id=ctx.inv.id)
            phase.execute(ctx, journal)

    def _complete(
        self,
        ctx: InvestigationContext,
        journal: InvestigationObserver,
        started,
    ) -> Investigation:
        inv = ctx.inv
        inv.status = InvestigationStatus.COMPLETED
        inv.completed_at = utcnow()
        inv.updated_at = utcnow()
        self.store.put_investigation(inv)
        journal.on_record(
            JournalRecordType.SUMMARY,
            "Investigation complete",
            inv.root_cause or inv.summary or "",
        )
        INVESTIGATIONS_COMPLETED.labels(status="COMPLETED").inc()
        duration = (utcnow() - started).total_seconds()
        INVESTIGATION_DURATION.observe(duration)
        log.info("investigation_complete", duration_s=duration, hypotheses=len(inv.hypotheses))
        return inv

    def _fail(self, inv: Investigation, exc: Exception) -> None:
        log.exception("investigation_failed")
        inv.status = InvestigationStatus.FAILED
        inv.error = str(exc)
        inv.completed_at = utcnow()
        inv.updated_at = utcnow()
        self.store.put_investigation(inv)
        JournalEmitter(self.store, inv).on_record(
            JournalRecordType.ERROR,
            "Investigation failed",
            str(exc),
        )
        INVESTIGATIONS_COMPLETED.labels(status="FAILED").inc()


def build_chat_loop() -> ToolLoop:
    """Factory helper for on-demand SRE chat (lighter tool surface)."""
    return ToolRegistryFactory().build_loop(agent_space_id="", mcp_server_ids=[], include_mcp=False)
