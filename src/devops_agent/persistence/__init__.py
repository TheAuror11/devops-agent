from __future__ import annotations

from functools import lru_cache

from devops_agent.config import settings
from devops_agent.persistence.memory import MemoryStore
from devops_agent.persistence.protocol import Store


@lru_cache
def get_store() -> Store:
    if settings.store_backend == "dynamodb":
        from devops_agent.persistence.dynamodb import DynamoStore

        return DynamoStore()
    return MemoryStore(settings.data_dir)
