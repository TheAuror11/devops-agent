from __future__ import annotations

from typing import Protocol

from devops_agent.domain.models import Runbook
from devops_agent.rag.index import RetrievedChunk, RunbookIndex


class RetrievalStrategy(Protocol):
    """Strategy pattern for runbook retrieval (BM25 today, OpenSearch later)."""

    def rebuild(self, runbooks: list[Runbook]) -> None: ...

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]: ...


class Bm25RetrievalStrategy:
    """Default local/dev Strategy wrapping RunbookIndex."""

    def __init__(self, index: RunbookIndex | None = None) -> None:
        self._index = index or RunbookIndex()

    def rebuild(self, runbooks: list[Runbook]) -> None:
        self._index.rebuild(runbooks)

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        return self._index.search(query, k=k)

    @property
    def index(self) -> RunbookIndex:
        return self._index


class OpenSearchRetrievalStrategy:
    """Production Adapter stub — falls back to BM25 until OPENSEARCH_ENDPOINT is wired."""

    def __init__(self, fallback: RetrievalStrategy | None = None) -> None:
        self._fallback = fallback or Bm25RetrievalStrategy()

    def rebuild(self, runbooks: list[Runbook]) -> None:
        self._fallback.rebuild(runbooks)

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        # Dense k-NN path reserved for OPENSEARCH_ENDPOINT + Titan embeddings.
        return self._fallback.search(query, k=k)


def build_retrieval_strategy() -> RetrievalStrategy:
    """Factory selecting retrieval Strategy from settings."""
    from devops_agent.config import settings

    if settings.opensearch_endpoint:
        return OpenSearchRetrievalStrategy()
    return Bm25RetrievalStrategy()
