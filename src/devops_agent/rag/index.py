from __future__ import annotations

import hashlib
import math
import re
from dataclasses import dataclass

from rank_bm25 import BM25Okapi

from devops_agent.domain.models import Runbook
from devops_agent.observability import get_logger

log = get_logger("rag")

_TOKEN = re.compile(r"[a-z0-9_./-]+")


def tokenize(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def chunk_text(text: str, size: int = 900, overlap: int = 120) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks: list[str] = []
    i = 0
    step = max(size - overlap, 1)
    while i < len(words):
        chunk = " ".join(words[i : i + size])
        chunks.append(chunk)
        i += step
    return chunks


@dataclass
class RetrievedChunk:
    runbook_id: str
    title: str
    path: str
    text: str
    score: float
    tags: list[str]


class RunbookIndex:
    """Hybrid RAG over operational runbooks.

    Local/dev uses BM25. Production can additionally embed chunks with
    Amazon Titan via Bedrock and query OpenSearch k-NN.
    """

    def __init__(self) -> None:
        self._chunks: list[RetrievedChunk] = []
        self._bm25: BM25Okapi | None = None
        self._tokenized: list[list[str]] = []

    def rebuild(self, runbooks: list[Runbook]) -> None:
        self._chunks = []
        for rb in runbooks:
            for i, chunk in enumerate(chunk_text(rb.content)):
                self._chunks.append(
                    RetrievedChunk(
                        runbook_id=rb.id,
                        title=rb.title,
                        path=f"{rb.path}#chunk-{i}",
                        text=chunk,
                        score=0.0,
                        tags=rb.tags,
                    )
                )
        self._tokenized = [tokenize(c.title + " " + " ".join(c.tags) + " " + c.text) for c in self._chunks]
        self._bm25 = BM25Okapi(self._tokenized) if self._tokenized else None
        log.info("runbook_index_rebuilt", chunks=len(self._chunks), runbooks=len(runbooks))

    def search(self, query: str, k: int = 5) -> list[RetrievedChunk]:
        if not self._chunks or not query.strip():
            return []
        q_tokens = tokenize(query)
        scores = list(self._bm25.get_scores(q_tokens)) if self._bm25 else [0.0] * len(self._chunks)
        ranked: list[tuple[float, RetrievedChunk]] = []
        qset = set(q_tokens)
        for score, chunk, tokens in zip(scores, self._chunks, self._tokenized, strict=True):
            overlap = len(qset & set(tokens))
            combined = float(score) + overlap
            if combined <= 0:
                continue
            ranked.append(
                (
                    combined,
                    RetrievedChunk(
                        runbook_id=chunk.runbook_id,
                        title=chunk.title,
                        path=chunk.path,
                        text=chunk.text,
                        score=combined,
                        tags=chunk.tags,
                    ),
                )
            )
        ranked.sort(key=lambda x: x[0], reverse=True)
        return [c for _, c in ranked[:k]]


def embedding_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)
