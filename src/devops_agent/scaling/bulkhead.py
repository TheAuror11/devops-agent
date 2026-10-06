from __future__ import annotations

import threading
from contextlib import contextmanager

from devops_agent.config import settings
from devops_agent.observability import get_logger

log = get_logger("bulkhead")

_bedrock_sem: threading.Semaphore | None = None
_tool_sem: threading.Semaphore | None = None
_lock = threading.Lock()


def _bedrock() -> threading.Semaphore:
    global _bedrock_sem
    with _lock:
        if _bedrock_sem is None:
            _bedrock_sem = threading.Semaphore(settings.bedrock_max_inflight_per_task)
        return _bedrock_sem


def _tools() -> threading.Semaphore:
    global _tool_sem
    with _lock:
        if _tool_sem is None:
            _tool_sem = threading.Semaphore(settings.tool_max_inflight_per_task)
        return _tool_sem


@contextmanager
def bedrock_slot():
    """Bulkhead: cap concurrent Bedrock Converse calls per worker task."""
    sem = _bedrock()
    acquired = sem.acquire(timeout=settings.bedrock_slot_timeout_seconds)
    if not acquired:
        raise TimeoutError("bedrock bulkhead saturated")
    try:
        yield
    finally:
        sem.release()


@contextmanager
def tool_slot():
    """Bulkhead: cap concurrent external tool/MCP calls per worker task."""
    sem = _tools()
    acquired = sem.acquire(timeout=30)
    if not acquired:
        raise TimeoutError("tool bulkhead saturated")
    try:
        yield
    finally:
        sem.release()
