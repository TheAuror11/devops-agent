from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from devops_agent.agents.prompts import (
    CHAT_SYSTEM,
    INVESTIGATION_SYSTEM,
    MITIGATION_SYSTEM,
    PREVENTION_SYSTEM,
    TRIAGE_SYSTEM,
    skills_block,
)
from devops_agent.agents.tool_loop import ToolLoop
from devops_agent.domain.models import (
    ChatMessage,
    Hypothesis,
    HypothesisStatus,
    Investigation,
    InvestigationStatus,
    JournalRecord,
    JournalRecordType,
    MitigationPlan,
    Recommendation,
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
from devops_agent.tools.builtin import builtin_tools

log = get_logger("orchestrator")

EventFn = Callable[[str, dict[str, Any]], None]


class InvestigationOrchestrator:
    """Multi-agent incident lifecycle: Triage → Investigation → Mitigation → Prevention.

    Mirrors AWS DevOps Agent capabilities sharing a topology graph and an
    immutable investigation journal.
    """

    def __init__(self, store: Store) -> None:
        self.store = store
        self.mcp = McpRegistry(store)

    def run(self, investigation_id: str) -> Investigation:
        inv = self.store.get_investigation(investigation_id)
        if inv is None:
            raise KeyError(investigation_id)
        investigation_id_var.set(inv.id)
        ACTIVE_INVESTIGATIONS.inc()
        started = utcnow()
        try:
            space = self.store.get_agent_space(inv.agent_space_id)
            skills = self.store.list_skills(inv.agent_space_id) if space else []
            skill_text = skills_block([f"### {s.name}\n{s.body}" for s in skills])
            mcp_tools = self.mcp.tools_for_space(space.mcp_server_ids if space else [])

            def emit(record_type: JournalRecordType, title: str, body: str = "", payload: dict | None = None) -> None:
                self.store.append_journal(
                    JournalRecord(
                        investigation_id=inv.id,
                        execution_id=inv.execution_id,
                        record_type=record_type,
                        title=title,
                        body=body,
                        payload=payload or {},
                    )
                )

            def on_event(kind: str, data: dict[str, Any]) -> None:
                if kind == "tool_call":
                    emit(
                        JournalRecordType.TOOL_CALL,
                        f"tool:{data.get('name')}",
                        body=str(data.get("result"))[:1500],
                        payload=data,
                    )
                    emit(JournalRecordType.EVIDENCE, f"evidence from {data.get('name')}", payload=data)
                elif kind == "model_text" and data.get("text"):
                    emit(JournalRecordType.EVIDENCE, "reasoning", body=data["text"][:2000])

            loop = ToolLoop(
                specs=builtin_tools(),
                mcp_tools=mcp_tools,
                mcp_registry=self.mcp,
                mcp_server_ids=space.mcp_server_ids if space else [],
                on_event=on_event,
            )

            emit(JournalRecordType.INVESTIGATION_STARTED, "Investigation started", inv.description)
            inv.status = InvestigationStatus.TRIAGE
            inv.started_at = utcnow()
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            emit(JournalRecordType.STATUS_CHANGE, "TRIAGE")

            brief = (
                f"Incident: {inv.title}\nDescription: {inv.description}\n"
                f"Starting point: {inv.starting_point}\nPriority: {inv.priority}\n"
                f"Account: {inv.account_id} Region: {inv.region}\n"
                f"Incident time: {inv.incident_time.isoformat()}\n{skill_text}"
            )
            triage_text = loop.run(TRIAGE_SYSTEM, brief)
            emit(JournalRecordType.TRIAGE_SUMMARY, "Triage complete", triage_text)
            emit(JournalRecordType.CORRELATION, "Alert correlation", triage_text)

            inv.status = InvestigationStatus.INVESTIGATING
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            emit(JournalRecordType.STATUS_CHANGE, "INVESTIGATING")
            emit(JournalRecordType.CONTEXT_ACQUIRED, "Context acquisition", "Walking topology and change window.")

            investigation_text = loop.run(
                INVESTIGATION_SYSTEM,
                brief + "\n\nTriage findings:\n" + triage_text,
            )
            inv.hypotheses = parse_hypotheses(investigation_text)
            inv.root_cause = parse_root_cause(investigation_text)
            inv.summary = investigation_text[:4000]
            emit(JournalRecordType.ROOT_CAUSE, "Root cause", inv.root_cause or investigation_text[:1500])
            for hyp in inv.hypotheses:
                emit(
                    JournalRecordType.HYPOTHESIS,
                    hyp.title,
                    hyp.statement,
                    {"status": hyp.status, "confidence": hyp.confidence},
                )

            inv.status = InvestigationStatus.MITIGATING
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            emit(JournalRecordType.STATUS_CHANGE, "MITIGATING")
            mitigation_text = loop.run(
                MITIGATION_SYSTEM,
                brief + "\n\nRoot cause:\n" + (inv.root_cause or investigation_text),
            )
            inv.mitigation = parse_mitigation(mitigation_text)
            emit(JournalRecordType.MITIGATION_PLAN, "Mitigation plan", mitigation_text)

            inv.status = InvestigationStatus.PREVENTION
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            emit(JournalRecordType.STATUS_CHANGE, "PREVENTION")
            prevention_text = loop.run(
                PREVENTION_SYSTEM,
                brief + "\n\nRoot cause:\n" + (inv.root_cause or "") + "\n\n" + investigation_text,
            )
            recs = parse_recommendations(prevention_text, inv)
            for rec in recs:
                self.store.put_recommendation(rec)
            emit(JournalRecordType.PREVENTION, "Prevention recommendations", prevention_text)

            inv.status = InvestigationStatus.COMPLETED
            inv.completed_at = utcnow()
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            emit(JournalRecordType.SUMMARY, "Investigation complete", inv.root_cause or inv.summary or "")
            INVESTIGATIONS_COMPLETED.labels(status="COMPLETED").inc()
            duration = (utcnow() - started).total_seconds()
            INVESTIGATION_DURATION.observe(duration)
            log.info("investigation_complete", duration_s=duration, hypotheses=len(inv.hypotheses))
            return inv
        except Exception as exc:
            log.exception("investigation_failed")
            inv.status = InvestigationStatus.FAILED
            inv.error = str(exc)
            inv.completed_at = utcnow()
            inv.updated_at = utcnow()
            self.store.put_investigation(inv)
            self.store.append_journal(
                JournalRecord(
                    investigation_id=inv.id,
                    execution_id=inv.execution_id,
                    record_type=JournalRecordType.ERROR,
                    title="Investigation failed",
                    body=str(exc),
                )
            )
            INVESTIGATIONS_COMPLETED.labels(status="FAILED").inc()
            raise
        finally:
            ACTIVE_INVESTIGATIONS.dec()

    def chat(self, investigation_id: str, content: str) -> ChatMessage:
        inv = self.store.get_investigation(investigation_id)
        if inv is None:
            raise KeyError(investigation_id)
        user_msg = ChatMessage(investigation_id=inv.id, role="user", content=content)
        self.store.put_chat(user_msg)
        self.store.append_journal(
            JournalRecord(
                investigation_id=inv.id,
                execution_id=inv.execution_id,
                record_type=JournalRecordType.OPERATOR_STEER,
                title="Operator message",
                body=content,
                actor="operator",
            )
        )
        journal = self.store.list_journal(inv.id)
        journal_txt = "\n".join(f"[{j.record_type}] {j.title}: {j.body[:400]}" for j in journal[-30:])
        loop = ToolLoop(specs=builtin_tools())
        reply = loop.run(
            CHAT_SYSTEM,
            f"Investigation {inv.title}\nStatus {inv.status}\nRoot cause: {inv.root_cause}\n"
            f"Journal:\n{journal_txt}\n\nOperator: {content}",
            max_rounds=4,
        )
        agent_msg = ChatMessage(investigation_id=inv.id, role="agent", content=reply)
        self.store.put_chat(agent_msg)
        self.store.append_journal(
            JournalRecord(
                investigation_id=inv.id,
                execution_id=inv.execution_id,
                record_type=JournalRecordType.CHAT,
                title="Agent reply",
                body=reply,
            )
        )
        return agent_msg


def parse_root_cause(text: str) -> str | None:
    m = re.search(r"ROOT_CAUSE:\s*(.+)", text, re.I | re.S)
    if not m:
        return None
    return m.group(1).split("HYPOTHESES:")[0].strip()[:2000]


def parse_hypotheses(text: str) -> list[Hypothesis]:
    block = text.split("HYPOTHESES:")[-1] if "HYPOTHESES:" in text.upper() or "HYPOTHESES:" in text else text
    hyps: list[Hypothesis] = []
    for line in block.splitlines():
        line = line.strip(" -*\t")
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        title = parts[0]
        status_raw = parts[1].replace(" ", "_").upper()
        try:
            status = HypothesisStatus(status_raw)
        except ValueError:
            mapped = {
                "ROOT CAUSE": HypothesisStatus.ROOT_CAUSE,
                "ROOT_CAUSE": HypothesisStatus.ROOT_CAUSE,
                "CAUSE": HypothesisStatus.CAUSE,
                "REFUTED": HypothesisStatus.REFUTED,
                "CANDIDATE": HypothesisStatus.CANDIDATE,
            }
            status = mapped.get(parts[1].upper(), HypothesisStatus.CANDIDATE)
        conf = 0.0
        if len(parts) >= 3:
            try:
                conf = float(parts[2])
            except ValueError:
                conf = 0.0
        statement = parts[3] if len(parts) > 3 else title
        if len(title) > 120:
            continue
        hyps.append(Hypothesis(title=title, statement=statement, status=status, confidence=conf))
    return hyps[:8]


def parse_mitigation(text: str) -> MitigationPlan:
    def section(name: str) -> list[str]:
        m = re.search(rf"{name}:?\s*(.+?)(?:\n[A-Z][a-zA-Z ]+:|\Z)", text, re.I | re.S)
        if not m:
            return []
        body = m.group(1)
        return [re.sub(r"^\d+\.\s*", "", ln).strip(" -") for ln in body.splitlines() if ln.strip()][:12]

    steps = section("Steps") or [ln.strip(" -") for ln in text.splitlines() if ln.strip().startswith(("1.", "2.", "3."))]
    return MitigationPlan(
        strategy=next((ln.strip() for ln in text.splitlines() if ln.lower().startswith("strategy")), "Restore service with reversible capacity and client changes.")[:500],
        steps=steps or ["Review plan with on-call before applying any write."],
        validation_checks=section("Validation checks") or section("Validation"),
        success_criteria=section("Success criteria"),
        rollback=section("Rollback"),
        blast_radius=" ".join(section("Blast radius")) or "See topology walk.",
    )


def parse_recommendations(text: str, inv: Investigation) -> list[Recommendation]:
    recs: list[Recommendation] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in re.sub(r"^\d+\s*\|", "", line).split("|")]
        if len(parts) < 3:
            continue
        category, title, rationale = parts[0], parts[1], parts[2]
        if category.lower() in {"category", "observability"} or len(title) > 8:
            effort = parts[3] if len(parts) > 3 else "medium"
            impact = parts[4] if len(parts) > 4 else "high"
            if effort not in {"low", "medium", "high"}:
                effort = "medium"
            if impact not in {"low", "medium", "high"}:
                impact = "high"
            recs.append(
                Recommendation(
                    agent_space_id=inv.agent_space_id,
                    investigation_id=inv.id,
                    category=category[:40],
                    title=title[:160],
                    rationale=rationale[:500],
                    effort=effort,  # type: ignore[arg-type]
                    impact=impact,  # type: ignore[arg-type]
                )
            )
    return recs[:10]
