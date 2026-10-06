from __future__ import annotations

from functools import lru_cache

from devops_agent.persistence import get_store
from devops_agent.rag.index import RunbookIndex


@lru_cache
def get_runbook_index() -> RunbookIndex:
    idx = RunbookIndex()
    idx.rebuild(get_store().list_runbooks())
    return idx


def refresh_runbook_index() -> RunbookIndex:
    get_runbook_index.cache_clear()
    return get_runbook_index()
