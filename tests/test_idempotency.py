from __future__ import annotations

from devops_agent.resilience.idempotency import DuplicateInvestigationError, IdempotencyStore


def test_claim_once() -> None:
    store = IdempotencyStore(ttl_seconds=60)
    assert store.claim("k1", "inv_a", "w1") is True
    assert store.claim("k1", "inv_a", "w1") is False
    try:
        store.claim("k1", "inv_b", "w2")
        raise AssertionError("expected duplicate")
    except DuplicateInvestigationError:
        pass
    store.complete("k1")
    assert store.claim("k1", "inv_a", "w1") is False
