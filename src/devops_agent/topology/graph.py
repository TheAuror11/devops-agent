from __future__ import annotations

from typing import Any

from devops_agent.persistence import get_store
from devops_agent.persistence.protocol import Store
from devops_agent.topology.context import agent_space_id_var


def walk(
    node_name: str,
    depth: int = 2,
    *,
    store: Store | None = None,
    space_id: str | None = None,
) -> dict[str, Any]:
    """Adapter over Store topology: blast-radius BFS from a named node.

    Prefer injecting `store` + `space_id`. Falls back to contextvar / first space
    for builtin tool compatibility.
    """
    store = store or get_store()
    resolved_space = space_id or agent_space_id_var.get() or ""
    if not resolved_space:
        spaces = store.list_agent_spaces()
        if not spaces:
            return {"nodes": [], "edges": [], "note": "no agent space"}
        resolved_space = spaces[0].id

    nodes = store.list_nodes(resolved_space)
    edges = store.list_edges(resolved_space)
    by_id = {n.id: n for n in nodes}
    start = next((n for n in nodes if n.name.lower() == node_name.lower() or n.id == node_name), None)
    if start is None:
        start = next((n for n in nodes if node_name.lower() in n.name.lower()), None)
    if start is None:
        return {
            "nodes": [{"id": n.id, "name": n.name, "kind": n.kind} for n in nodes],
            "edges": [{"source": e.source_id, "target": e.target_id, "kind": e.kind} for e in edges],
            "note": "name not found; returning full graph",
            "agent_space_id": resolved_space,
        }

    seen = {start.id}
    frontier = {start.id}
    for _ in range(max(depth, 1)):
        nxt: set[str] = set()
        for e in edges:
            if e.source_id in frontier or e.target_id in frontier:
                nxt.add(e.source_id)
                nxt.add(e.target_id)
        seen |= nxt
        frontier = nxt

    subgraph_nodes = [by_id[i] for i in seen if i in by_id]
    subgraph_edges = [e for e in edges if e.source_id in seen and e.target_id in seen]
    return {
        "origin": {"id": start.id, "name": start.name, "kind": start.kind},
        "blast_radius": [n.name for n in subgraph_nodes],
        "agent_space_id": resolved_space,
        "nodes": [
            {"id": n.id, "name": n.name, "kind": n.kind, "arn": n.arn, "attributes": n.attributes}
            for n in subgraph_nodes
        ],
        "edges": [
            {
                "source": by_id.get(e.source_id).name if e.source_id in by_id else e.source_id,
                "target": by_id.get(e.target_id).name if e.target_id in by_id else e.target_id,
                "kind": e.kind,
            }
            for e in subgraph_edges
        ],
    }
