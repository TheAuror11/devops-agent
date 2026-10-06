from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from devops_agent.domain.models import Priority


class CreateAgentSpaceRequest(BaseModel):
    name: str
    description: str = ""
    accounts: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"])
    slack_channel: str | None = None
    mcp_server_ids: list[str] = Field(default_factory=list)


class CreateInvestigationRequest(BaseModel):
    agent_space_id: str
    title: str
    description: str
    priority: Priority = Priority.HIGH
    starting_point: str = "manual"
    incident_time: datetime | None = None
    account_id: str | None = None
    region: str | None = None
    affected_resources: list[str] = Field(default_factory=list)
    idempotency_key: str | None = None
    source: str = "api"


class ChatRequest(BaseModel):
    content: str


class CreateSkillRequest(BaseModel):
    name: str
    description: str
    body: str
    targets: list[str] = Field(default_factory=lambda: ["investigation"])


class CreateRunbookRequest(BaseModel):
    title: str
    content: str
    tags: list[str] = Field(default_factory=list)
    path: str = "inline.md"
    agent_space_id: str


class RegisterMcpRequest(BaseModel):
    name: str
    endpoint: str
    description: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    read_only: bool = True


class UpdateRecommendationRequest(BaseModel):
    status: str
    note: str | None = None
