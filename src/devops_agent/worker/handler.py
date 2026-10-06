from __future__ import annotations

import os
import socket

from devops_agent.agents.orchestrator import InvestigationOrchestrator
from devops_agent.domain.models import InvestigationStatus
from devops_agent.observability import QUEUE_IN_FLIGHT, get_logger, investigation_id_var
from devops_agent.persistence.protocol import Store
from devops_agent.queueing import QueueMessage
from devops_agent.resilience.idempotency import IdempotencyStore

log = get_logger("worker.handler")


class InvestigationHandler:
    def __init__(self, store: Store, idem: IdempotencyStore) -> None:
        self.store = store
        self.idem = idem
        self.orch = InvestigationOrchestrator(store)
        self.owner = f"{socket.gethostname()}:{os.getpid()}"

    def handle(self, message: QueueMessage) -> None:
        inv_id = message.body.get("investigation_id")
        if not inv_id:
            log.warning("message_missing_investigation_id", body=message.body)
            return
        investigation_id_var.set(inv_id)
        key = f"process:{inv_id}"
        claimed = self.idem.claim(key, inv_id, self.owner)
        if not claimed:
            rec = self.idem.get(key)
            if rec and rec.completed:
                log.info("skip_completed", investigation_id=inv_id)
                return
            inv = self.store.get_investigation(inv_id)
            if inv and inv.status in {
                InvestigationStatus.COMPLETED,
                InvestigationStatus.FAILED,
                InvestigationStatus.CANCELLED,
            }:
                self.idem.complete(key)
                return
            log.info("already_in_flight", investigation_id=inv_id)
            return
        QUEUE_IN_FLIGHT.inc()
        try:
            inv = self.store.get_investigation(inv_id)
            if inv is None:
                log.error("investigation_missing", investigation_id=inv_id)
                return
            if inv.status == InvestigationStatus.CANCELLED:
                self.idem.complete(key)
                return
            self.orch.run(inv_id)
            self.idem.complete(key)
        finally:
            QUEUE_IN_FLIGHT.dec()
            investigation_id_var.set("")
