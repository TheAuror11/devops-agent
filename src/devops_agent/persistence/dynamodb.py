from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from boto3.dynamodb.conditions import Key
from pydantic import BaseModel

from devops_agent.config import settings
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


def _to_ddb(value: Any) -> Any:
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _to_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_to_ddb(v) for v in value]
    return value


def _from_ddb(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value) if value % 1 else int(value)
    if isinstance(value, dict):
        return {k: _from_ddb(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_from_ddb(v) for v in value]
    return value


class DynamoStore:
    """Single-table DynamoDB adapter. PK/SK design documented in docs/ARCHITECTURE.md."""

    def __init__(self, table_name: str | None = None, resource: Any = None) -> None:
        import boto3

        self.table_name = table_name or f"{settings.ddb_table_prefix}-store"
        self._resource = resource or boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self._resource.Table(self.table_name)

    def _put(self, item: dict[str, Any]) -> None:
        self.table.put_item(Item=_to_ddb(item))

    def _get(self, pk: str, sk: str) -> dict[str, Any] | None:
        resp = self.table.get_item(Key={"pk": pk, "sk": sk})
        item = resp.get("Item")
        return _from_ddb(item) if item else None

    def _query(self, pk: str, sk_prefix: str | None = None) -> list[dict[str, Any]]:
        kwargs: dict[str, Any] = {"KeyConditionExpression": Key("pk").eq(pk)}
        if sk_prefix:
            kwargs["KeyConditionExpression"] = Key("pk").eq(pk) & Key("sk").begins_with(sk_prefix)
        items: list[dict[str, Any]] = []
        while True:
            resp = self.table.query(**kwargs)
            items.extend(_from_ddb(i) for i in resp.get("Items", []))
            if "LastEvaluatedKey" not in resp:
                break
            kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]
        return items

    def _model_item(self, pk: str, sk: str, entity: str, model: BaseModel) -> dict[str, Any]:
        data = model.model_dump(mode="json")
        data.update({"pk": pk, "sk": sk, "entity": entity})
        return data

    def put_agent_space(self, space: AgentSpace) -> AgentSpace:
        self._put(self._model_item("SPACE", f"SPACE#{space.id}", "AgentSpace", space))
        return space

    def get_agent_space(self, space_id: str) -> AgentSpace | None:
        item = self._get("SPACE", f"SPACE#{space_id}")
        return AgentSpace.model_validate(item) if item else None

    def list_agent_spaces(self) -> list[AgentSpace]:
        return [AgentSpace.model_validate(i) for i in self._query("SPACE", "SPACE#")]

    def delete_agent_space(self, space_id: str) -> None:
        self.table.delete_item(Key={"pk": "SPACE", "sk": f"SPACE#{space_id}"})

    def put_investigation(self, inv: Investigation) -> Investigation:
        self._put(self._model_item(f"SPACE#{inv.agent_space_id}", f"INV#{inv.id}", "Investigation", inv))
        self._put(self._model_item("INV", f"INV#{inv.id}", "Investigation", inv))
        return inv

    def get_investigation(self, inv_id: str) -> Investigation | None:
        item = self._get("INV", f"INV#{inv_id}")
        return Investigation.model_validate(item) if item else None

    def list_investigations(self, space_id: str | None = None) -> list[Investigation]:
        if space_id:
            items = self._query(f"SPACE#{space_id}", "INV#")
        else:
            items = self._query("INV", "INV#")
        return [Investigation.model_validate(i) for i in items]

    def append_journal(self, record: JournalRecord) -> JournalRecord:
        sk = f"JRNL#{record.created_at.isoformat()}#{record.id}"
        self._put(self._model_item(f"INV#{record.investigation_id}", sk, "Journal", record))
        return record

    def list_journal(self, investigation_id: str, after_id: str | None = None) -> list[JournalRecord]:
        items = self._query(f"INV#{investigation_id}", "JRNL#")
        records = [JournalRecord.model_validate(i) for i in items]
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
        self._put(self._model_item(f"SPACE#{skill.agent_space_id}", f"SKILL#{skill.id}", "Skill", skill))
        return skill

    def list_skills(self, space_id: str) -> list[Skill]:
        return [Skill.model_validate(i) for i in self._query(f"SPACE#{space_id}", "SKILL#")]

    def put_runbook(self, runbook: Runbook) -> Runbook:
        self._put(self._model_item(f"SPACE#{runbook.agent_space_id}", f"RB#{runbook.id}", "Runbook", runbook))
        self._put(self._model_item("RB", f"RB#{runbook.id}", "Runbook", runbook))
        return runbook

    def get_runbook(self, runbook_id: str) -> Runbook | None:
        item = self._get("RB", f"RB#{runbook_id}")
        return Runbook.model_validate(item) if item else None

    def list_runbooks(self, space_id: str | None = None) -> list[Runbook]:
        if space_id:
            items = self._query(f"SPACE#{space_id}", "RB#") + self._query("SPACE#*", "RB#")
        else:
            items = self._query("RB", "RB#")
        return [Runbook.model_validate(i) for i in items]

    def put_mcp(self, server: McpServer) -> McpServer:
        self._put(self._model_item("MCP", f"MCP#{server.id}", "McpServer", server))
        return server

    def get_mcp(self, server_id: str) -> McpServer | None:
        item = self._get("MCP", f"MCP#{server_id}")
        return McpServer.model_validate(item) if item else None

    def list_mcp(self) -> list[McpServer]:
        return [McpServer.model_validate(i) for i in self._query("MCP", "MCP#")]

    def put_node(self, node: TopologyNode) -> TopologyNode:
        self._put(self._model_item(f"SPACE#{node.agent_space_id}", f"NODE#{node.id}", "Node", node))
        self._put(self._model_item("NODE", f"NODE#{node.id}", "Node", node))
        return node

    def put_edge(self, edge: TopologyEdge) -> TopologyEdge:
        self._put(self._model_item(f"SPACE#{edge.agent_space_id}", f"EDGE#{edge.id}", "Edge", edge))
        return edge

    def list_nodes(self, space_id: str) -> list[TopologyNode]:
        return [TopologyNode.model_validate(i) for i in self._query(f"SPACE#{space_id}", "NODE#")]

    def list_edges(self, space_id: str) -> list[TopologyEdge]:
        return [TopologyEdge.model_validate(i) for i in self._query(f"SPACE#{space_id}", "EDGE#")]

    def get_node(self, node_id: str) -> TopologyNode | None:
        item = self._get("NODE", f"NODE#{node_id}")
        return TopologyNode.model_validate(item) if item else None

    def put_recommendation(self, rec: Recommendation) -> Recommendation:
        self._put(self._model_item(f"SPACE#{rec.agent_space_id}", f"REC#{rec.id}", "Rec", rec))
        self._put(self._model_item("REC", f"REC#{rec.id}", "Rec", rec))
        return rec

    def list_recommendations(self, space_id: str | None = None) -> list[Recommendation]:
        if space_id:
            items = self._query(f"SPACE#{space_id}", "REC#")
        else:
            items = self._query("REC", "REC#")
        return [Recommendation.model_validate(i) for i in items]

    def get_recommendation(self, rec_id: str) -> Recommendation | None:
        item = self._get("REC", f"REC#{rec_id}")
        return Recommendation.model_validate(item) if item else None

    def put_chat(self, msg: ChatMessage) -> ChatMessage:
        sk = f"CHAT#{msg.created_at.isoformat()}#{msg.id}"
        self._put(self._model_item(f"INV#{msg.investigation_id}", sk, "Chat", msg))
        return msg

    def list_chat(self, investigation_id: str) -> list[ChatMessage]:
        return [ChatMessage.model_validate(i) for i in self._query(f"INV#{investigation_id}", "CHAT#")]
