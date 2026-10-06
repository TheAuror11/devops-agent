from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from devops_agent.config import settings
from devops_agent.observability import QUEUE_DEPTH, QUEUE_OLDEST_AGE, get_logger
from devops_agent.queueing import InvestigationQueue

log = get_logger("backpressure")


@dataclass
class QueuePressure:
    visible: int
    in_flight: int
    oldest_age_seconds: int
    overloaded: bool
    reason: str = ""


class TokenBucket:
    """Simple per-key rate limiter for API / webhook ingress."""

    def __init__(self, rate_per_minute: int) -> None:
        self.rate = max(rate_per_minute, 1)
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        window = 60.0
        with self._lock:
            q = self._hits.setdefault(key, deque())
            while q and now - q[0] > window:
                q.popleft()
            if len(q) >= self.rate:
                return False
            q.append(now)
            return True


_rate_limiter: TokenBucket | None = None


def get_rate_limiter() -> TokenBucket:
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = TokenBucket(settings.max_investigations_per_minute)
    return _rate_limiter


def assess_queue_pressure(q: InvestigationQueue) -> QueuePressure:
    attrs = getattr(q, "attributes", None)
    if not callable(attrs):
        return QueuePressure(visible=0, in_flight=0, oldest_age_seconds=0, overloaded=False)
    data = attrs()
    visible = int(data.get("ApproximateNumberOfMessages", 0))
    in_flight = int(data.get("ApproximateNumberOfMessagesNotVisible", 0))
    oldest = int(data.get("ApproximateAgeOfOldestMessage", 0))
    QUEUE_DEPTH.set(visible)
    QUEUE_OLDEST_AGE.set(oldest)

    overloaded = False
    reason = ""
    if settings.max_queue_depth > 0 and visible >= settings.max_queue_depth:
        overloaded = True
        reason = f"queue depth {visible} >= {settings.max_queue_depth}"
    elif settings.max_queue_age_seconds > 0 and oldest >= settings.max_queue_age_seconds:
        overloaded = True
        reason = f"oldest message age {oldest}s >= {settings.max_queue_age_seconds}s"
    if overloaded:
        log.warning("backpressure_active", reason=reason, visible=visible, oldest=oldest)
    return QueuePressure(
        visible=visible,
        in_flight=in_flight,
        oldest_age_seconds=oldest,
        overloaded=overloaded,
        reason=reason,
    )
