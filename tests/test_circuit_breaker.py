from __future__ import annotations

from devops_agent.resilience.circuit_breaker import CircuitBreakerRegistry


def test_opens_after_threshold() -> None:
    cb = CircuitBreakerRegistry(failure_threshold=3, reset_seconds=0.01)
    assert cb.allow("cloudwatch")
    cb.record_failure("cloudwatch")
    cb.record_failure("cloudwatch")
    assert cb.allow("cloudwatch")
    cb.record_failure("cloudwatch")
    assert not cb.allow("cloudwatch")
    assert cb.snapshot()["cloudwatch"] == "open"


def test_recovers_to_half_open() -> None:
    import time

    cb = CircuitBreakerRegistry(failure_threshold=1, reset_seconds=0.02)
    cb.record_failure("logs")
    assert not cb.allow("logs")
    time.sleep(0.03)
    assert cb.allow("logs")
    cb.record_success("logs")
    assert cb.snapshot()["logs"] == "closed"
