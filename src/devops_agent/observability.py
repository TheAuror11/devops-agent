from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Any

import structlog
from prometheus_client import Counter, Gauge, Histogram

correlation_id_var: ContextVar[str] = ContextVar("correlation_id", default="")
investigation_id_var: ContextVar[str] = ContextVar("investigation_id", default="")

INVESTIGATIONS_STARTED = Counter(
    "devops_agent_investigations_started_total", "Investigations enqueued", ["priority"]
)
INVESTIGATIONS_COMPLETED = Counter(
    "devops_agent_investigations_completed_total", "Investigations finished", ["status"]
)
INVESTIGATION_DURATION = Histogram(
    "devops_agent_investigation_duration_seconds",
    "End-to-end investigation duration",
    buckets=(5, 15, 30, 60, 120, 300, 480, 600, 900),
)
TOOL_CALLS = Counter(
    "devops_agent_tool_calls_total", "Tool invocations", ["tool", "status"]
)
TOOL_LATENCY = Histogram(
    "devops_agent_tool_latency_seconds", "Tool call latency", ["tool"]
)
BEDROCK_CALLS = Counter("devops_agent_bedrock_calls_total", "Bedrock converse calls", ["stop_reason"])
CIRCUIT_STATE = Gauge("devops_agent_circuit_open", "Circuit breaker open (1) or closed (0)", ["provider"])
ACTIVE_INVESTIGATIONS = Gauge("devops_agent_active_investigations", "In-flight investigations on this worker")
QUEUE_IN_FLIGHT = Gauge("devops_agent_queue_in_flight", "Messages currently being processed")
QUEUE_DEPTH = Gauge("devops_agent_queue_depth", "Approximate visible SQS messages")
QUEUE_OLDEST_AGE = Gauge("devops_agent_queue_oldest_age_seconds", "Age of oldest visible SQS message")
BACKPRESSURE_REJECTS = Counter(
    "devops_agent_backpressure_rejects_total", "Investigations rejected by backpressure/rate limit", ["reason"]
)


def new_correlation_id() -> str:
    cid = str(uuid.uuid4())
    correlation_id_var.set(cid)
    return cid


def configure_logging(level: str = "INFO") -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _inject_ids,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(getattr(logging, level.upper(), logging.INFO)),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def _inject_ids(logger: Any, method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    cid = correlation_id_var.get()
    iid = investigation_id_var.get()
    if cid:
        event_dict["correlation_id"] = cid
    if iid:
        event_dict["investigation_id"] = iid
    return event_dict


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
