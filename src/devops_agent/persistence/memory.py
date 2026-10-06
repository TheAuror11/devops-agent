from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from devops_agent.domain.models import (
    AgentSpace,
    ChatMessage,
    Investigation,
    JournalRecord,
    McpServer,
    Recommendation,
    Runbook,
    Skill,
    TopologyEdge,
    TopologyNode,
)


class MemoryStore:
    """Thread-safe JSON-backed store used for local/dev and tests.

    Production swaps this for DynamoDB via the same Store protocol.
    """

    def __init__(self, data_dir: str = "./data") -> None:
        self._lock = threading.RLock()
        self._dir = Path(data_dir)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.agent_spaces: dict[str, AgentSpace] = {}
        self.investigations: dict[str, Investigation] = {}
        self.journal: dict[str, list[JournalRecord]] = {}
        self.skills: dict[str, Skill] = {}
        self.runbooks: dict[str, Runbook] = {}
        self.mcp: dict[str, McpServer] = {}
        self.nodes: dict[str, TopologyNode] = {}
        self.edges: dict[str, TopologyEdge] = {}
        self.recommendations: dict[str, Recommendation] = {}
        self.chat: dict[str, list[ChatMessage]] = {}
        self._load()

    def _path(self, name: str) -> Path:
        return self._dir / f"{name}.json"

    def _dump_models(self, items: dict[str, BaseModel]) -> list[dict[str, Any]]:
        return [v.model_dump(mode="json") for v in items.values()]

    def _persist(self) -> None:
        from devops_agent.config import settings as app_settings

        if app_settings.app_env == "test":
            return
        payloads = {
            "agent_spaces": self._dump_models(self.agent_spaces),
            "investigations": self._dump_models(self.investigations),
            "journal": {
                k: [r.model_dump(mode="json") for r in v] for k, v in self.journal.items()
            },
            "skills": self._dump_models(self.skills),
            "runbooks": self._dump_models(self.runbooks),
            "mcp": self._dump_models(self.mcp),
            "nodes": self._dump_models(self.nodes),
            "edges": self._dump_models(self.edges),
            "recommendations": self._dump_models(self.recommendations),
            "chat": {k: [m.model_dump(mode="json") for m in v] for k, v in self.chat.items()},
        }
        tmp = self._path("store.tmp")
        tmp.write_text(json.dumps(payloads, indent=2, default=str))
        tmp.replace(self._path("store"))

    def _load(self) -> None:
        path = self._path("store")
        if not path.exists():
            return
        raw = json.loads(path.read_text())
        self.agent_spaces = {i["id"]: AgentSpace.model_validate(i) for i in raw.get("agent_spaces", [])}
        self.investigations = {i["id"]: Investigation.model_validate(i) for i in raw.get("investigations", [])}
        self.journal = {
            k: [JournalRecord.model_validate(r) for r in v] for k, v in raw.get("journal", {}).items()
        }
        self.skills = {i["id"]: Skill.model_validate(i) for i in raw.get("skills", [])}
        self.runbooks = {i["id"]: Runbook.model_validate(i) for i in raw.get("runbooks", [])}
        self.mcp = {i["id"]: McpServer.model_validate(i) for i in raw.get("mcp", [])}
        self.nodes = {i["id"]: TopologyNode.model_validate(i) for i in raw.get("nodes", [])}
        self.edges = {i["id"]: TopologyEdge.model_validate(i) for i in raw.get("edges", [])}
        self.recommendations = {
            i["id"]: Recommendation.model_validate(i) for i in raw.get("recommendations", [])
        }
        self.chat = {
            k: [ChatMessage.model_validate(m) for m in v] for k, v in raw.get("chat", {}).items()
        }

    def put_agent_space(self, space: AgentSpace) -> AgentSpace:
        with self._lock:
            self.agent_spaces[space.id] = space
            self._persist()
            return space

    def get_agent_space(self, space_id: str) -> AgentSpace | None:
        return self.agent_spaces.get(space_id)

    def list_agent_spaces(self) -> list[AgentSpace]:
        return sorted(self.agent_spaces.values(), key=lambda s: s.created_at, reverse=True)

    def delete_agent_space(self, space_id: str) -> None:
        with self._lock:
            self.agent_spaces.pop(space_id, None)
            self._persist()

    def put_investigation(self, inv: Investigation) -> Investigation:
        with self._lock:
            self.investigations[inv.id] = inv
            self._persist()
            return inv

    def get_investigation(self, inv_id: str) -> Investigation | None:
        return self.investigations.get(inv_id)

    def list_investigations(self, space_id: str | None = None) -> list[Investigation]:
        items = list(self.investigations.values())
        if space_id:
            items = [i for i in items if i.agent_space_id == space_id]
        return sorted(items, key=lambda i: i.created_at, reverse=True)

    def append_journal(self, record: JournalRecord) -> JournalRecord:
        with self._lock:
            self.journal.setdefault(record.investigation_id, []).append(record)
            self._persist()
            return record

    def list_journal(self, investigation_id: str, after_id: str | None = None) -> list[JournalRecord]:
        records = list(self.journal.get(investigation_id, []))
        if after_id:
            seen = False
            out: list[JournalRecord] = []
            for r in records:
                if seen:
                    out.append(r)
                elif r.id == after_id:
                    seen = True
            return out
        return records

    def put_skill(self, skill: Skill) -> Skill:
        with self._lock:
            self.skills[skill.id] = skill
            self._persist()
            return skill

    def list_skills(self, space_id: str) -> list[Skill]:
        return [s for s in self.skills.values() if s.agent_space_id == space_id]

    def put_runbook(self, runbook: Runbook) -> Runbook:
        with self._lock:
            self.runbooks[runbook.id] = runbook
            self._persist()
            return runbook

    def get_runbook(self, runbook_id: str) -> Runbook | None:
        return self.runbooks.get(runbook_id)

    def list_runbooks(self, space_id: str | None = None) -> list[Runbook]:
        items = list(self.runbooks.values())
        if space_id:
            items = [r for r in items if r.agent_space_id in {space_id, "*"}]
        return items

    def put_mcp(self, server: McpServer) -> McpServer:
        with self._lock:
            self.mcp[server.id] = server
            self._persist()
            return server

    def get_mcp(self, server_id: str) -> McpServer | None:
        return self.mcp.get(server_id)

    def list_mcp(self) -> list[McpServer]:
        return list(self.mcp.values())

    def put_node(self, node: TopologyNode) -> TopologyNode:
        with self._lock:
            self.nodes[node.id] = node
            self._persist()
            return node

    def put_edge(self, edge: TopologyEdge) -> TopologyEdge:
        with self._lock:
            self.edges[edge.id] = edge
            self._persist()
            return edge

    def list_nodes(self, space_id: str) -> list[TopologyNode]:
        return [n for n in self.nodes.values() if n.agent_space_id == space_id]

    def list_edges(self, space_id: str) -> list[TopologyEdge]:
        return [e for e in self.edges.values() if e.agent_space_id == space_id]

    def get_node(self, node_id: str) -> TopologyNode | None:
        return self.nodes.get(node_id)

    def put_recommendation(self, rec: Recommendation) -> Recommendation:
        with self._lock:
            self.recommendations[rec.id] = rec
            self._persist()
            return rec

    def list_recommendations(self, space_id: str | None = None) -> list[Recommendation]:
        items = list(self.recommendations.values())
        if space_id:
            items = [r for r in items if r.agent_space_id == space_id]
        return sorted(items, key=lambda r: r.created_at, reverse=True)

    def get_recommendation(self, rec_id: str) -> Recommendation | None:
        return self.recommendations.get(rec_id)

    def put_chat(self, msg: ChatMessage) -> ChatMessage:
        with self._lock:
            self.chat.setdefault(msg.investigation_id, []).append(msg)
            self._persist()
            return msg

    def list_chat(self, investigation_id: str) -> list[ChatMessage]:
        return list(self.chat.get(investigation_id, []))
