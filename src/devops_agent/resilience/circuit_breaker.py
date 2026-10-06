from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from enum import StrEnum

from devops_agent.observability import CIRCUIT_STATE, get_logger

log = get_logger("circuit")


class CircuitState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitOpenError(RuntimeError):
    def __init__(self, provider: str) -> None:
        super().__init__(f"circuit open for provider '{provider}'")
        self.provider = provider


@dataclass
class _Window:
    failures: int = 0
    successes: int = 0
    opened_at: float = 0.0
    state: CircuitState = CircuitState.CLOSED


class CircuitBreakerRegistry:
    """Per-capability-provider circuit breakers.

    Open circuits skip the provider and let the investigation continue with
    degraded evidence rather than stalling the whole RCA.
    """

    def __init__(self, failure_threshold: int = 5, reset_seconds: float = 30.0) -> None:
        self.failure_threshold = failure_threshold
        self.reset_seconds = reset_seconds
        self._windows: dict[str, _Window] = {}
        self._lock = threading.Lock()

    def _window(self, provider: str) -> _Window:
        if provider not in self._windows:
            self._windows[provider] = _Window()
            CIRCUIT_STATE.labels(provider=provider).set(0)
        return self._windows[provider]

    def allow(self, provider: str) -> bool:
        with self._lock:
            w = self._window(provider)
            if w.state == CircuitState.CLOSED:
                return True
            if w.state == CircuitState.OPEN:
                if time.monotonic() - w.opened_at >= self.reset_seconds:
                    w.state = CircuitState.HALF_OPEN
                    log.info("circuit_half_open", provider=provider)
                    return True
                return False
            return True

    def record_success(self, provider: str) -> None:
        with self._lock:
            w = self._window(provider)
            w.failures = 0
            w.successes += 1
            if w.state != CircuitState.CLOSED:
                w.state = CircuitState.CLOSED
                CIRCUIT_STATE.labels(provider=provider).set(0)
                log.info("circuit_closed", provider=provider)

    def record_failure(self, provider: str) -> None:
        with self._lock:
            w = self._window(provider)
            w.failures += 1
            if w.state == CircuitState.HALF_OPEN or w.failures >= self.failure_threshold:
                w.state = CircuitState.OPEN
                w.opened_at = time.monotonic()
                CIRCUIT_STATE.labels(provider=provider).set(1)
                log.warning("circuit_open", provider=provider, failures=w.failures)

    def snapshot(self) -> dict[str, str]:
        with self._lock:
            return {k: v.state.value for k, v in self._windows.items()}


_registry: CircuitBreakerRegistry | None = None


def get_circuit_registry() -> CircuitBreakerRegistry:
    global _registry
    if _registry is None:
        from devops_agent.config import settings

        _registry = CircuitBreakerRegistry(
            failure_threshold=settings.circuit_breaker_failure_threshold,
            reset_seconds=settings.circuit_breaker_reset_seconds,
        )
    return _registry
