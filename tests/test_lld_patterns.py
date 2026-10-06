from __future__ import annotations

from devops_agent.agents.journal import JournalEmitter
from devops_agent.agents.phases import default_phase_pipeline
from devops_agent.agents.workflow import InvestigationWorkflow
from devops_agent.domain.models import AgentSpace, Investigation, JournalRecordType, Priority
from devops_agent.persistence.memory import MemoryStore
from devops_agent.rag.strategy import Bm25RetrievalStrategy, build_retrieval_strategy
from devops_agent.tools.registry import ToolRegistryFactory
from devops_agent.topology.graph import walk


def test_phase_pipeline_order() -> None:
    names = [p.name for p in default_phase_pipeline()]
    assert names == ["triage", "investigate", "mitigate", "prevent"]


def test_tool_registry_factory_dispatch() -> None:
    factory = ToolRegistryFactory()
    registry = factory.build_registry(agent_space_id="as_test", include_mcp=False)
    assert "list_alarms" in registry.specs
    assert "retrieve_runbooks" in registry.specs
    result = registry.dispatch("list_alarms", {"state": "ALARM"})
    assert "alarms" in result


def test_retrieval_strategy_factory() -> None:
    strategy = build_retrieval_strategy()
    assert isinstance(strategy, Bm25RetrievalStrategy)


def test_journal_observer_and_topology_adapter() -> None:
    store = MemoryStore(data_dir="/tmp/devops-agent-lld-test")
    space = store.put_agent_space(AgentSpace(id="as_lld", name="lld-space"))
    from devops_agent.domain.models import EdgeKind, NodeKind, TopologyEdge, TopologyNode

    store.put_node(
        TopologyNode(
            id="n1",
            agent_space_id=space.id,
            kind=NodeKind.ECS_SERVICE,
            name="checkout-api",
        )
    )
    store.put_node(
        TopologyNode(
            id="n2",
            agent_space_id=space.id,
            kind=NodeKind.DYNAMODB,
            name="Orders",
        )
    )
    store.put_edge(
        TopologyEdge(
            agent_space_id=space.id,
            source_id="n1",
            target_id="n2",
            kind=EdgeKind.WRITES_TO,
        )
    )
    graph = walk("checkout-api", depth=1, store=store, space_id=space.id)
    assert graph["origin"]["name"] == "checkout-api"
    assert "Orders" in graph["blast_radius"]

    inv = store.put_investigation(
        Investigation(
            agent_space_id=space.id,
            title="lld",
            description="test",
            priority=Priority.HIGH,
        )
    )
    journal = JournalEmitter(store, inv)
    journal.on_record(JournalRecordType.TRIAGE_SUMMARY, "ok", "body")
    journal.on_event("tool_call", {"name": "list_alarms", "result": {"alarms": []}})
    rows = store.list_journal(inv.id)
    types = {r.record_type for r in rows}
    assert JournalRecordType.TRIAGE_SUMMARY in types
    assert JournalRecordType.TOOL_CALL in types
    assert JournalRecordType.EVIDENCE in types


def test_workflow_facade_completes() -> None:
    from devops_agent.demo.seed import seed
    from devops_agent.persistence import get_store
    from devops_agent.rag import refresh_runbook_index

    store = get_store()
    space = seed()
    refresh_runbook_index()
    inv = store.put_investigation(
        Investigation(
            agent_space_id=space.id,
            title="Checkout p95 latency cliff",
            description="Orders timing out",
            priority=Priority.HIGH,
            starting_point="Latest alarm",
        )
    )
    result = InvestigationWorkflow(store).run(inv.id)
    assert result.status.value == "COMPLETED"
    assert result.root_cause
    assert result.hypotheses
