from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:16]}"


class Priority(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class InvestigationStatus(StrEnum):
    QUEUED = "QUEUED"
    TRIAGE = "TRIAGE"
    INVESTIGATING = "INVESTIGATING"
    MITIGATING = "MITIGATING"
    PREVENTION = "PREVENTION"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class HypothesisStatus(StrEnum):
    CANDIDATE = "CANDIDATE"
    SUPPORTING = "SUPPORTING"
    REFUTED = "REFUTED"
    CAUSE = "CAUSE"
    ROOT_CAUSE = "ROOT_CAUSE"


class JournalRecordType(StrEnum):
    INVESTIGATION_STARTED = "investigation_started"
    TRIAGE_SUMMARY = "triage_summary"
    CORRELATION = "correlation"
    CONTEXT_ACQUIRED = "context_acquired"
    EVIDENCE = "evidence"
    HYPOTHESIS = "hypothesis"
    TOOL_CALL = "tool_call"
    OPERATOR_STEER = "operator_steer"
    ROOT_CAUSE = "root_cause"
    MITIGATION_PLAN = "mitigation_plan"
    PREVENTION = "prevention"
    STATUS_CHANGE = "status_change"
    CHAT = "chat"
    ERROR = "error"
    SUMMARY = "summary"


class NodeKind(StrEnum):
    SERVICE = "service"
    LAMBDA = "lambda"
    ECS_SERVICE = "ecs_service"
    EKS_DEPLOYMENT = "eks_deployment"
    RDS = "rds"
    DYNAMODB = "dynamodb"
    ALB = "alb"
    API_GATEWAY = "api_gateway"
    SQS = "sqs"
    SNS = "sns"
    S3 = "s3"
    CLOUDFRONT = "cloudfront"
    ALARM = "alarm"
    LOG_GROUP = "log_group"
    PIPELINE = "pipeline"
    REPO = "repo"
    EXTERNAL = "external"


class EdgeKind(StrEnum):
    DEPENDS_ON = "depends_on"
    CALLS = "calls"
    WRITES_TO = "writes_to"
    READS_FROM = "reads_from"
    DEPLOYED_BY = "deployed_by"
    ALARMS_ON = "alarms_on"
    LOGS_TO = "logs_to"
    PRODUCES = "produces"
    CONSUMES = "consumes"


class CapabilityKind(StrEnum):
    CLOUDWATCH = "cloudwatch"
    LOGS = "logs"
    XRAY = "xray"
    CLOUDTRAIL = "cloudtrail"
    ECS = "ecs"
    LAMBDA = "lambda"
    RDS = "rds"
    DYNAMODB = "dynamodb"
    EKS = "eks"
    CONFIG = "config"
    GITHUB = "github"
    GITLAB = "gitlab"
    SLACK = "slack"
    PAGERDUTY = "pagerduty"
    SERVICENOW = "servicenow"
    MCP = "mcp"
    RUNBOOKS = "runbooks"
    TOPOLOGY = "topology"


class Hypothesis(BaseModel):
    id: str = Field(default_factory=lambda: new_id("hyp"))
    title: str
    statement: str
    status: HypothesisStatus = HypothesisStatus.CANDIDATE
    confidence: float = 0.0
    supporting_evidence: list[str] = Field(default_factory=list)
    counter_evidence: list[str] = Field(default_factory=list)
    source: str = "investigation"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class JournalRecord(BaseModel):
    id: str = Field(default_factory=lambda: new_id("jrnl"))
    investigation_id: str
    execution_id: str
    record_type: JournalRecordType
    title: str
    body: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    actor: str = "agent"
    created_at: datetime = Field(default_factory=utcnow)


class MitigationPlan(BaseModel):
    strategy: str
    steps: list[str]
    validation_checks: list[str]
    success_criteria: list[str]
    rollback: list[str]
    blast_radius: str
    execute: Literal[False] = False
    notes: str = "Agent recommends only. Operators execute remediations."


class Recommendation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rec"))
    agent_space_id: str
    investigation_id: str | None = None
    category: str
    title: str
    rationale: str
    effort: Literal["low", "medium", "high"] = "medium"
    impact: Literal["low", "medium", "high"] = "high"
    status: Literal["open", "accepted", "rejected", "implemented"] = "open"
    created_at: datetime = Field(default_factory=utcnow)


class Skill(BaseModel):
    id: str = Field(default_factory=lambda: new_id("skill"))
    agent_space_id: str
    name: str
    description: str
    body: str
    kind: Literal["custom", "learned"] = "custom"
    targets: list[str] = Field(default_factory=lambda: ["investigation"])
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Runbook(BaseModel):
    id: str = Field(default_factory=lambda: new_id("rb"))
    agent_space_id: str
    title: str
    path: str
    content: str
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class McpServer(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mcp"))
    name: str
    endpoint: str
    description: str = ""
    allowed_tools: list[str] = Field(default_factory=list)
    read_only: bool = True
    enabled: bool = True
    headers: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utcnow)


class TopologyNode(BaseModel):
    id: str
    agent_space_id: str
    kind: NodeKind
    name: str
    arn: str | None = None
    account_id: str | None = None
    region: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)
    attributes: dict[str, Any] = Field(default_factory=dict)
    discovered_at: datetime = Field(default_factory=utcnow)


class TopologyEdge(BaseModel):
    id: str = Field(default_factory=lambda: new_id("edge"))
    agent_space_id: str
    source_id: str
    target_id: str
    kind: EdgeKind
    attributes: dict[str, Any] = Field(default_factory=dict)


class AgentSpace(BaseModel):
    id: str = Field(default_factory=lambda: new_id("as"))
    name: str
    description: str = ""
    accounts: list[str] = Field(default_factory=list)
    regions: list[str] = Field(default_factory=lambda: ["us-east-1"])
    capabilities: list[CapabilityKind] = Field(default_factory=list)
    mcp_server_ids: list[str] = Field(default_factory=list)
    iam_role_arn: str | None = None
    slack_channel: str | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class Investigation(BaseModel):
    id: str = Field(default_factory=lambda: new_id("inv"))
    agent_space_id: str
    execution_id: str = Field(default_factory=lambda: new_id("exec"))
    title: str
    description: str
    status: InvestigationStatus = InvestigationStatus.QUEUED
    priority: Priority = Priority.HIGH
    starting_point: str = "manual"
    incident_time: datetime = Field(default_factory=utcnow)
    account_id: str | None = None
    region: str | None = None
    affected_resources: list[str] = Field(default_factory=list)
    correlated_alert_ids: list[str] = Field(default_factory=list)
    hypotheses: list[Hypothesis] = Field(default_factory=list)
    root_cause: str | None = None
    summary: str | None = None
    mitigation: MitigationPlan | None = None
    idempotency_key: str | None = None
    source: str = "api"
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error: str | None = None


class ChatMessage(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg"))
    investigation_id: str
    role: Literal["user", "agent", "system"]
    content: str
    created_at: datetime = Field(default_factory=utcnow)


class WebhookEvent(BaseModel):
    id: str = Field(default_factory=lambda: new_id("wh"))
    source: str
    payload: dict[str, Any]
    received_at: datetime = Field(default_factory=utcnow)
    investigation_id: str | None = None
