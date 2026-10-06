from __future__ import annotations

from functools import lru_cache

from devops_agent.config import settings
from devops_agent.queueing import InMemoryQueue, InvestigationQueue, SqsQueue

_local_queue: InMemoryQueue | None = None


@lru_cache
def get_queue() -> InvestigationQueue:
    global _local_queue
    if settings.queue_backend == "sqs" and settings.sqs_investigation_queue_url:
        return SqsQueue(settings.sqs_investigation_queue_url)
    if _local_queue is None:
        _local_queue = InMemoryQueue()
    return _local_queue


def reset_queue_cache() -> None:
    get_queue.cache_clear()
