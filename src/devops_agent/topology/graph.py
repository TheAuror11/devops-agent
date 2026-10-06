from __future__ import annotations

from typing import Any

from devops_agent.persistence import get_store


def walk(node_name: str, depth: int = 2) -> dict[str, Any]:
    store = get_store()
    spaces = store.list_agent_spaces()
    if not spaces:
        return {"nodes": [], "edges": [], "note": "no agent space"}
    space_id = spaces[0].id
    nodes = store.list_nodes(space_id)
    edges = store.list_edges(space_id)
    by_id = {n.id: n for n in nodes}
    start = next((n for n in nodes if n.name.lower() == node_name.lower() or n.id == node_name), None)
    if start is None:
        start = next((n for n in nodes if node_name.lower() in n.name.lower()), None)
    if start is None:
        return {
            "nodes": [{"id": n.id, "name": n.name, "kind": n.kind} for n in nodes],
            "edges": [{"source": e.source_id, "target": e.target_id, "kind": e.kind} for e in edges],
            "note": "name not found; returning full graph",
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
        frontier = nxt - seen if False else nxt

    subgraph_nodes = [by_id[i] for i in seen if i in by_id]
    subgraph_edges = [e for e in edges if e.source_id in seen and e.target_id in seen]
    return {
        "origin": {"id": start.id, "name": start.name, "kind": start.kind},
        "blast_radius": [n.name for n in subgraph_nodes],
        "nodes": [
            {"id": n.id, "name": n.name, "kind": n.kind, "arn": n.arn, "attributes": n.attributes}
            for n in subgraph_nodes
        ],
        "edges": [
            {"source": by_id.get(e.source_id).name if e.source_id in by_id else e.source_id,
             "target": by_id.get(e.target_id).name if e.target_id in by_id else e.target_id,
             "kind": e.kind}
            for e in subgraph_edges
        ],
    }
