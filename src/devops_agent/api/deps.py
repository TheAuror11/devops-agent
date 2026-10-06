from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from devops_agent.config import settings
from devops_agent.persistence import get_store
from devops_agent.persistence.protocol import Store
from devops_agent.resilience.idempotency import IdempotencyBackend, build_idempotency_store

_idem: IdempotencyBackend | None = None


def get_idempotency() -> IdempotencyBackend:
    global _idem
    if _idem is None:
        _idem = build_idempotency_store(settings.idempotency_ttl_seconds)
    return _idem


def require_api_key(x_api_key: Annotated[str | None, Header()] = None) -> str:
    if settings.is_local and not x_api_key:
        return "dev-local-key"
    if not x_api_key or x_api_key not in settings.api_key_set:
        raise HTTPException(status_code=401, detail="invalid api key")
    return x_api_key


StoreDep = Annotated[Store, Depends(get_store)]
AuthDep = Annotated[str, Depends(require_api_key)]
IdemDep = Annotated[IdempotencyBackend, Depends(get_idempotency)]
