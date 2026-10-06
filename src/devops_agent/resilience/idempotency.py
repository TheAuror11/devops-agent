from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass

from devops_agent.observability import get_logger

log = get_logger("idempotency")


class DuplicateInvestigationError(RuntimeError):
    def __init__(self, key: str, investigation_id: str) -> None:
        super().__init__(f"idempotency key '{key}' already claimed by {investigation_id}")
        self.key = key
        self.investigation_id = investigation_id


@dataclass
class IdempotencyRecord:
    key: str
    investigation_id: str
    owner: str
    expires_at: float
    completed: bool = False


class IdempotencyStore:
    """Exactly-once claim for investigation processing.

    SQS is at-least-once. Workers take a conditional lock on
    `investigation_id` (or a caller-supplied idempotency key) before running
    the orchestrator. Completing the lock lets retries no-op.
    """

    def __init__(self, ttl_seconds: int = 86400) -> None:
        self.ttl_seconds = ttl_seconds
        self._records: dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()

    def claim(self, key: str, investigation_id: str, owner: str) -> bool:
        now = time.time()
        with self._lock:
            existing = self._records.get(key)
            if existing and existing.expires_at > now:
                if existing.completed or existing.investigation_id == investigation_id:
                    log.info("idempotency_hit", key=key, investigation_id=investigation_id)
                    return False
                raise DuplicateInvestigationError(key, existing.investigation_id)
            self._records[key] = IdempotencyRecord(
                key=key,
                investigation_id=investigation_id,
                owner=owner,
                expires_at=now + self.ttl_seconds,
            )
            return True

    def complete(self, key: str) -> None:
        with self._lock:
            rec = self._records.get(key)
            if rec:
                rec.completed = True

    def get(self, key: str) -> IdempotencyRecord | None:
        with self._lock:
            rec = self._records.get(key)
            if rec and rec.expires_at > time.time():
                return rec
            return None


def fingerprint(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
