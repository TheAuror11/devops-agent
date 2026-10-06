from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Protocol

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


class IdempotencyBackend(Protocol):
    def claim(self, key: str, investigation_id: str, owner: str) -> bool: ...

    def complete(self, key: str) -> None: ...

    def get(self, key: str) -> IdempotencyRecord | None: ...


class IdempotencyStore:
    """Exactly-once claim for investigation create/process.

    Process-local by default. Production multi-task workers must use
    `DynamoIdempotencyStore` via `build_idempotency_store()`.
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


class DynamoIdempotencyStore:
    """Distributed lease via DynamoDB conditional writes (cross-task safe)."""

    def __init__(self, table_name: str | None = None, ttl_seconds: int = 86400, resource=None) -> None:
        import boto3
        from botocore.exceptions import ClientError

        from devops_agent.config import settings

        self.ttl_seconds = ttl_seconds
        self.table_name = table_name or f"{settings.ddb_table_prefix}-store"
        self._resource = resource or boto3.resource("dynamodb", region_name=settings.aws_region)
        self.table = self._resource.Table(self.table_name)
        self._ClientError = ClientError

    def _keys(self, key: str) -> dict[str, str]:
        return {"pk": "IDEM", "sk": f"IDEM#{key}"}

    def claim(self, key: str, investigation_id: str, owner: str) -> bool:
        now = int(time.time())
        expires = now + self.ttl_seconds
        item = {
            **self._keys(key),
            "entity": "Idempotency",
            "key": key,
            "investigation_id": investigation_id,
            "owner": owner,
            "completed": False,
            "expires_at": expires,
            "ttl": expires,
        }
        try:
            self.table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
                ExpressionAttributeValues={":now": now},
            )
            return True
        except self._ClientError as exc:
            if exc.response.get("Error", {}).get("Code") != "ConditionalCheckFailedException":
                raise
            existing = self.get(key)
            if existing is None:
                # Race: expired between put and get — retry once
                try:
                    self.table.put_item(
                        Item=item,
                        ConditionExpression="attribute_not_exists(pk) OR expires_at < :now",
                        ExpressionAttributeValues={":now": int(time.time())},
                    )
                    return True
                except self._ClientError:
                    existing = self.get(key)
            if existing and (existing.completed or existing.investigation_id == investigation_id):
                log.info("idempotency_hit", key=key, investigation_id=investigation_id)
                return False
            if existing:
                raise DuplicateInvestigationError(key, existing.investigation_id) from None
            log.info("idempotency_hit", key=key, investigation_id=investigation_id)
            return False

    def complete(self, key: str) -> None:
        now = int(time.time())
        self.table.update_item(
            Key=self._keys(key),
            UpdateExpression="SET completed = :t, expires_at = :e, #ttl = :e",
            ExpressionAttributeNames={"#ttl": "ttl"},
            ExpressionAttributeValues={":t": True, ":e": now + self.ttl_seconds},
        )

    def get(self, key: str) -> IdempotencyRecord | None:
        resp = self.table.get_item(Key=self._keys(key))
        item = resp.get("Item")
        if not item:
            return None
        expires = float(item.get("expires_at", 0))
        if expires <= time.time():
            return None
        return IdempotencyRecord(
            key=key,
            investigation_id=str(item.get("investigation_id", "")),
            owner=str(item.get("owner", "")),
            expires_at=expires,
            completed=bool(item.get("completed", False)),
        )


def build_idempotency_store(ttl_seconds: int | None = None) -> IdempotencyStore | DynamoIdempotencyStore:
    from devops_agent.config import settings

    ttl = ttl_seconds if ttl_seconds is not None else settings.idempotency_ttl_seconds
    if settings.store_backend == "dynamodb" and settings.app_env == "prod":
        return DynamoIdempotencyStore(ttl_seconds=ttl)
    return IdempotencyStore(ttl_seconds=ttl)


def fingerprint(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()
