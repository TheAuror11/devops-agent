from __future__ import annotations

from pathlib import Path

from devops_agent.config import settings
from devops_agent.domain.models import (
    AgentSpace,
    CapabilityKind,
    EdgeKind,
    McpServer,
    NodeKind,
    Runbook,
    Skill,
    TopologyEdge,
    TopologyNode,
    new_id,
    utcnow,
)
from devops_agent.persistence import get_store
from devops_agent.rag import refresh_runbook_index

RUNBOOKS_DIR = Path(__file__).resolve().parents[3] / "runbooks"

SPACE_ID = "as_retail_checkout"


def seed() -> AgentSpace:
    store = get_store()
    existing = store.get_agent_space(SPACE_ID)
    space = existing or AgentSpace(
        id=SPACE_ID,
        name="retail-checkout-prod",
        description="On-call boundary for the retail checkout platform (UI, checkout, payments, orders, catalog).",
        accounts=["123456789012"],
        regions=["us-east-1"],
        capabilities=[
            CapabilityKind.CLOUDWATCH,
            CapabilityKind.LOGS,
            CapabilityKind.XRAY,
            CapabilityKind.CLOUDTRAIL,
            CapabilityKind.ECS,
            CapabilityKind.LAMBDA,
            CapabilityKind.DYNAMODB,
            CapabilityKind.GITHUB,
            CapabilityKind.SLACK,
            CapabilityKind.MCP,
            CapabilityKind.RUNBOOKS,
            CapabilityKind.TOPOLOGY,
        ],
        slack_channel="#checkout-incidents",
        iam_role_arn="arn:aws:iam::123456789012:role/DevOpsAgentRole-AgentSpace",
    )
    store.put_agent_space(space)

    mcp = McpServer(
        id="mcp_demo_apm",
        name="org-apm",
        endpoint="http://127.0.0.1:8090/mcp",
        description="BYO MCP — Grafana/Prometheus-style APM latency and SLO error budget.",
        allowed_tools=["query_apm_latency", "query_error_budget"],
        read_only=True,
    )
    store.put_mcp(mcp)
    if mcp.id not in space.mcp_server_ids:
        space.mcp_server_ids.append(mcp.id)
        space.updated_at = utcnow()
        store.put_agent_space(space)

    _seed_topology(space.id)
    _seed_runbooks(space.id)
    _seed_skills(space.id)
    refresh_runbook_index()
    return space


def _seed_skills(space_id: str) -> None:
    store = get_store()
    if store.list_skills(space_id):
        return
    store.put_skill(
        Skill(
            agent_space_id=space_id,
            name="checkout-investigation",
            description="How to investigate checkout latency and order failures.",
            body=(
                "Start with topology walk from checkout-api. Always evaluate at least three hypotheses: "
                "recent deploy, downstream dependency, and resource saturation (pool, WCU, CPU). "
                "Payment latency that starts AFTER checkout onset is a symptom. "
                "Use retrieve_runbooks for DynamoDB throttling and connection pool runbooks. "
                "Call MCP query_apm_latency for p95 vs baseline."
            ),
            targets=["investigation", "triage"],
        )
    )
    store.put_skill(
        Skill(
            agent_space_id=space_id,
            name="mitigation-safety",
            description="Never execute write remediations. Always include rollback.",
            body=(
                "Generate mitigation plans with validation checks, success criteria, and rollback. "
                "Assess blast radius via the topology graph. Do not invoke mutating AWS APIs."
            ),
            targets=["mitigation"],
        )
    )


def _seed_runbooks(space_id: str) -> None:
    store = get_store()
    if store.list_runbooks(space_id):
        return
    loaded = False
    if RUNBOOKS_DIR.exists():
        for path in sorted(RUNBOOKS_DIR.glob("*.md")):
            store.put_runbook(
                Runbook(
                    agent_space_id=space_id,
                    title=path.stem.replace("-", " ").title(),
                    path=str(path.name),
                    content=path.read_text(),
                    tags=_tags_from_name(path.stem),
                )
            )
            loaded = True
    if not loaded:
        store.put_runbook(
            Runbook(
                agent_space_id=space_id,
                title="DynamoDB throttling connection pool",
                path="dynamodb-throttling-connection-pool.md",
                content=(
                    "ProvisionedThroughputExceededException and connection pool waiters mean "
                    "raise WCU before scaling compute. Payment latency after onset is a symptom."
                ),
                tags=["dynamodb", "throttling", "pool", "checkout"],
            )
        )


def _tags_from_name(stem: str) -> list[str]:
    parts = stem.split("-")
    return list(dict.fromkeys(parts + ["runbook"]))


def _seed_topology(space_id: str) -> None:
    store = get_store()
    if store.list_nodes(space_id):
        return
    region = "us-east-1"
    account = "123456789012"
    nodes = [
        TopologyNode(
            id="n_alb",
            agent_space_id=space_id,
            kind=NodeKind.ALB,
            name="checkout-alb",
            arn=f"arn:aws:elasticloadbalancing:{region}:{account}:loadbalancer/app/checkout/1",
            account_id=account,
            region=region,
            tags={"app": "checkout", "env": "prod"},
        ),
        TopologyNode(
            id="n_checkout",
            agent_space_id=space_id,
            kind=NodeKind.ECS_SERVICE,
            name="checkout-api",
            arn=f"arn:aws:ecs:{region}:{account}:service/retail/checkout-api",
            account_id=account,
            region=region,
            tags={"app": "checkout", "env": "prod"},
            attributes={"pool_size": 50, "timeout_ms": 8000},
        ),
        TopologyNode(
            id="n_payments",
            agent_space_id=space_id,
            kind=NodeKind.ECS_SERVICE,
            name="payments-api",
            arn=f"arn:aws:ecs:{region}:{account}:service/retail/payments-api",
            account_id=account,
            region=region,
            tags={"app": "payments", "env": "prod"},
        ),
        TopologyNode(
            id="n_orders_ddb",
            agent_space_id=space_id,
            kind=NodeKind.DYNAMODB,
            name="Orders",
            arn=f"arn:aws:dynamodb:{region}:{account}:table/Orders",
            account_id=account,
            region=region,
            tags={"app": "checkout", "env": "prod"},
            attributes={"wcu": 800, "billing": "PROVISIONED"},
        ),
        TopologyNode(
            id="n_catalog",
            agent_space_id=space_id,
            kind=NodeKind.ECS_SERVICE,
            name="catalog-api",
            account_id=account,
            region=region,
            tags={"app": "catalog", "env": "prod"},
        ),
        TopologyNode(
            id="n_lambda_faulty",
            agent_space_id=space_id,
            kind=NodeKind.LAMBDA,
            name="FaultyDemoFunction",
            arn=f"arn:aws:lambda:{region}:{account}:function:FaultyDemoFunction",
            account_id=account,
            region=region,
            tags={"app": "demo"},
        ),
        TopologyNode(
            id="n_alarm_lat",
            agent_space_id=space_id,
            kind=NodeKind.ALARM,
            name="checkout-p95-latency",
            account_id=account,
            region=region,
        ),
        TopologyNode(
            id="n_logs",
            agent_space_id=space_id,
            kind=NodeKind.LOG_GROUP,
            name="/ecs/checkout-api",
            account_id=account,
            region=region,
        ),
        TopologyNode(
            id="n_pipeline",
            agent_space_id=space_id,
            kind=NodeKind.PIPELINE,
            name="checkout-cd",
            attributes={"provider": "github-actions"},
        ),
        TopologyNode(
            id="n_repo",
            agent_space_id=space_id,
            kind=NodeKind.REPO,
            name="retail/checkout",
            attributes={"default_branch": "main"},
        ),
    ]
    for n in nodes:
        store.put_node(n)

    def edge(src: str, dst: str, kind: EdgeKind) -> None:
        store.put_edge(
            TopologyEdge(
                id=new_id("edge"),
                agent_space_id=space_id,
                source_id=src,
                target_id=dst,
                kind=kind,
            )
        )

    edge("n_alb", "n_checkout", EdgeKind.CALLS)
    edge("n_checkout", "n_orders_ddb", EdgeKind.WRITES_TO)
    edge("n_checkout", "n_payments", EdgeKind.CALLS)
    edge("n_checkout", "n_catalog", EdgeKind.CALLS)
    edge("n_alarm_lat", "n_checkout", EdgeKind.ALARMS_ON)
    edge("n_checkout", "n_logs", EdgeKind.LOGS_TO)
    edge("n_checkout", "n_pipeline", EdgeKind.DEPLOYED_BY)
    edge("n_pipeline", "n_repo", EdgeKind.DEPENDS_ON)


def main() -> None:
    space = seed()
    print(f"Seeded Agent Space {space.id} ({space.name}) into {settings.data_dir}")


if __name__ == "__main__":
    main()
