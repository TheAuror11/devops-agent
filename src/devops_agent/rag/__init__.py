from __future__ import annotations

from functools import lru_cache

from devops_agent.persistence import get_store
from devops_agent.rag.index import RunbookIndex
from devops_agent.rag.strategy import RetrievalStrategy, build_retrieval_strategy


@lru_cache
def get_retrieval_strategy() -> RetrievalStrategy:
    strategy = build_retrieval_strategy()
    strategy.rebuild(get_store().list_runbooks())
    return strategy


@lru_cache
def get_runbook_index() -> RunbookIndex:
    """Backward-compatible access to the BM25 index behind the Strategy."""
    strategy = get_retrieval_strategy()
    index = getattr(strategy, "index", None)
    if isinstance(index, RunbookIndex):
        return index
    # OpenSearch (or other) Strategy — rebuild a BM25 view for callers that need it.
    idx = RunbookIndex()
    idx.rebuild(get_store().list_runbooks())
    return idx


def refresh_runbook_index() -> RunbookIndex:
    get_retrieval_strategy.cache_clear()
    get_runbook_index.cache_clear()
    get_retrieval_strategy()
    return get_runbook_index()
