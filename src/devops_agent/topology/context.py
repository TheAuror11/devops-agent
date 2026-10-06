from __future__ import annotations

from contextvars import ContextVar

agent_space_id_var: ContextVar[str] = ContextVar("agent_space_id", default="")
