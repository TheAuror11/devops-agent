from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from devops_agent.agents.orchestrator import InvestigationOrchestrator
from devops_agent.api.deps import AuthDep, IdemDep, StoreDep
from devops_agent.api.schemas import (
    ChatRequest,
    CreateAgentSpaceRequest,
    CreateInvestigationRequest,
    CreateRunbookRequest,
    CreateSkillRequest,
    RegisterMcpRequest,
    UpdateRecommendationRequest,
)
from devops_agent.config import settings
from devops_agent.domain.models import (
    AgentSpace,
    CapabilityKind,
    Investigation,
    InvestigationStatus,
    Priority,
    Recommendation,
    Runbook,
    Skill,
    utcnow,
)
from devops_agent.observability import INVESTIGATIONS_STARTED, get_logger
from devops_agent.rag import refresh_runbook_index
from devops_agent.resilience.circuit_breaker import get_circuit_registry
from devops_agent.runtime import get_queue

log = get_logger("api")
router = APIRouter(prefix="/v1")


@router.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "env": settings.app_env,
        "bedrock": settings.use_bedrock,
        "store": settings.store_backend,
        "queue": settings.queue_backend,
        "circuits": get_circuit_registry().snapshot(),
    }


@router.get("/agent-spaces")
def list_spaces(store: StoreDep, _: AuthDep) -> list[AgentSpace]:
    return store.list_agent_spaces()


@router.post("/agent-spaces", status_code=201)
def create_space(body: CreateAgentSpaceRequest, store: StoreDep, _: AuthDep) -> AgentSpace:
    space = AgentSpace(
        name=body.name,
        description=body.description,
        accounts=body.accounts,
        regions=body.regions,
        slack_channel=body.slack_channel,
        mcp_server_ids=body.mcp_server_ids,
        capabilities=list(CapabilityKind),
    )
    return store.put_agent_space(space)


@router.get("/agent-spaces/{space_id}")
def get_space(space_id: str, store: StoreDep, _: AuthDep) -> AgentSpace:
    space = store.get_agent_space(space_id)
    if not space:
        raise HTTPException(404, "agent space not found")
    return space


@router.get("/agent-spaces/{space_id}/topology")
def get_topology(space_id: str, store: StoreDep, _: AuthDep) -> dict[str, Any]:
    if not store.get_agent_space(space_id):
        raise HTTPException(404, "agent space not found")
    nodes = store.list_nodes(space_id)
    edges = store.list_edges(space_id)
    return {
        "nodes": [n.model_dump(mode="json") for n in nodes],
        "edges": [e.model_dump(mode="json") for e in edges],
    }


@router.get("/agent-spaces/{space_id}/skills")
def list_skills(space_id: str, store: StoreDep, _: AuthDep) -> list[Skill]:
    return store.list_skills(space_id)


@router.post("/agent-spaces/{space_id}/skills", status_code=201)
def create_skill(space_id: str, body: CreateSkillRequest, store: StoreDep, _: AuthDep) -> Skill:
    if not store.get_agent_space(space_id):
        raise HTTPException(404, "agent space not found")
    return store.put_skill(
        Skill(
            agent_space_id=space_id,
            name=body.name,
            description=body.description,
            body=body.body,
            targets=body.targets,
        )
    )


@router.post("/investigations", status_code=202)
def create_investigation(
    body: CreateInvestigationRequest,
    store: StoreDep,
    idem: IdemDep,
    _: AuthDep,
) -> Investigation:
    if not store.get_agent_space(body.agent_space_id):
        raise HTTPException(404, "agent space not found")
    key = body.idempotency_key or f"inv:{body.agent_space_id}:{body.title}:{body.description[:80]}"
    create_key = f"create:{key}"
    existing = idem.get(create_key)
    if existing:
        found = store.get_investigation(existing.investigation_id)
        if found:
            return found
    inv = Investigation(
        agent_space_id=body.agent_space_id,
        title=body.title,
        description=body.description,
        priority=body.priority,
        starting_point=body.starting_point,
        incident_time=body.incident_time or utcnow(),
        account_id=body.account_id,
        region=body.region,
        affected_resources=body.affected_resources,
        idempotency_key=key,
        source=body.source,
    )
    claimed = idem.claim(create_key, inv.id, owner="api")
    if not claimed:
        rec = idem.get(create_key)
        if rec:
            found = store.get_investigation(rec.investigation_id)
            if found:
                return found
    store.put_investigation(inv)
    get_queue().enqueue(
        {
            "investigation_id": inv.id,
            "agent_space_id": inv.agent_space_id,
            "idempotency_key": key,
        },
        dedup_id=inv.id,
    )
    INVESTIGATIONS_STARTED.labels(priority=inv.priority.value).inc()
    log.info("investigation_enqueued", investigation_id=inv.id)
    return inv


@router.get("/investigations")
def list_investigations(
    store: StoreDep,
    _: AuthDep,
    agent_space_id: str | None = None,
) -> list[Investigation]:
    return store.list_investigations(agent_space_id)


@router.get("/investigations/{inv_id}")
def get_investigation(inv_id: str, store: StoreDep, _: AuthDep) -> Investigation:
    inv = store.get_investigation(inv_id)
    if not inv:
        raise HTTPException(404, "investigation not found")
    return inv


@router.post("/investigations/{inv_id}/cancel")
def cancel_investigation(inv_id: str, store: StoreDep, _: AuthDep) -> Investigation:
    inv = store.get_investigation(inv_id)
    if not inv:
        raise HTTPException(404, "investigation not found")
    if inv.status in {InvestigationStatus.COMPLETED, InvestigationStatus.FAILED}:
        return inv
    inv.status = InvestigationStatus.CANCELLED
    inv.updated_at = utcnow()
    return store.put_investigation(inv)


@router.get("/investigations/{inv_id}/journal")
def list_journal(
    inv_id: str,
    store: StoreDep,
    _: AuthDep,
    after_id: str | None = Query(default=None),
) -> list[Any]:
    if not store.get_investigation(inv_id):
        raise HTTPException(404, "investigation not found")
    return [r.model_dump(mode="json") for r in store.list_journal(inv_id, after_id)]


@router.get("/investigations/{inv_id}/chat")
def list_chat(inv_id: str, store: StoreDep, _: AuthDep) -> list[Any]:
    return [m.model_dump(mode="json") for m in store.list_chat(inv_id)]


@router.post("/investigations/{inv_id}/chat")
def chat(inv_id: str, body: ChatRequest, store: StoreDep, _: AuthDep) -> Any:
    orch = InvestigationOrchestrator(store)
    try:
        msg = orch.chat(inv_id, body.content)
    except KeyError:
        raise HTTPException(404, "investigation not found") from None
    return msg


@router.get("/runbooks")
def list_runbooks(store: StoreDep, _: AuthDep, agent_space_id: str | None = None) -> list[Runbook]:
    return store.list_runbooks(agent_space_id)


@router.post("/runbooks", status_code=201)
def create_runbook(body: CreateRunbookRequest, store: StoreDep, _: AuthDep) -> Runbook:
    rb = store.put_runbook(
        Runbook(
            agent_space_id=body.agent_space_id,
            title=body.title,
            path=body.path,
            content=body.content,
            tags=body.tags,
        )
    )
    refresh_runbook_index()
    return rb


@router.get("/mcp/servers")
def list_mcp(store: StoreDep, _: AuthDep) -> list[Any]:
    return [s.model_dump(mode="json") for s in store.list_mcp()]


@router.post("/mcp/servers", status_code=201)
def register_mcp(body: RegisterMcpRequest, store: StoreDep, _: AuthDep) -> Any:
    from devops_agent.domain.models import McpServer

    if not settings.is_local and not body.endpoint.startswith("https://"):
        raise HTTPException(400, "MCP endpoints must be HTTPS in production")
    server = McpServer(
        name=body.name,
        endpoint=body.endpoint,
        description=body.description,
        allowed_tools=body.allowed_tools,
        read_only=body.read_only,
    )
    return store.put_mcp(server)


@router.get("/recommendations")
def list_recs(store: StoreDep, _: AuthDep, agent_space_id: str | None = None) -> list[Recommendation]:
    return store.list_recommendations(agent_space_id)


@router.patch("/recommendations/{rec_id}")
def update_rec(
    rec_id: str, body: UpdateRecommendationRequest, store: StoreDep, _: AuthDep
) -> Recommendation:
    rec = store.get_recommendation(rec_id)
    if not rec:
        raise HTTPException(404, "recommendation not found")
    rec.status = body.status  # type: ignore[assignment]
    return store.put_recommendation(rec)


@router.post("/webhooks/{source}")
def webhook(source: str, payload: dict[str, Any], store: StoreDep, _: AuthDep) -> Investigation:
    """CloudWatch / PagerDuty / generic webhook → investigation enqueue."""
    title, description, priority = _parse_webhook(source, payload)
    spaces = store.list_agent_spaces()
    if not spaces:
        raise HTTPException(400, "no agent space configured")
    space = spaces[0]
    body = CreateInvestigationRequest(
        agent_space_id=space.id,
        title=title,
        description=description,
        priority=priority,
        starting_point=f"webhook:{source}",
        source=source,
        idempotency_key=f"wh:{source}:{payload.get('alarmName') or payload.get('incident_key') or payload.get('id')}",
    )
    return create_investigation(body, store, get_idempotency_from_dep(), _)


def get_idempotency_from_dep() -> IdemDep:
    from devops_agent.api.deps import get_idempotency

    return get_idempotency()


def _parse_webhook(source: str, payload: dict[str, Any]) -> tuple[str, str, Priority]:
    src = source.lower()
    if src in {"cloudwatch", "aws"}:
        msg = payload.get("Message") or payload
        if isinstance(msg, str):
            title = "CloudWatch alarm"
            description = msg[:2000]
        else:
            title = str(msg.get("AlarmName") or payload.get("AlarmName") or "CloudWatch alarm")
            description = str(msg.get("NewStateReason") or payload.get("NewStateReason") or payload)
        return title, description[:4000], Priority.HIGH
    if src in {"pagerduty", "pd"}:
        event = (payload.get("event") or payload).get("data") if isinstance(payload.get("event"), dict) else payload
        title = str((event or {}).get("title") or payload.get("title") or "PagerDuty incident")
        description = str((event or {}).get("body") or payload)
        return title, description[:4000], Priority.CRITICAL
    title = str(payload.get("title") or payload.get("alarm") or f"{source} alert")
    description = str(payload.get("description") or payload)
    return title, description[:4000], Priority.HIGH
