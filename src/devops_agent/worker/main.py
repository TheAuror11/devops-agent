from __future__ import annotations

import signal
import time

from devops_agent.api.deps import get_idempotency
from devops_agent.config import settings
from devops_agent.observability import configure_logging, get_logger
from devops_agent.persistence import get_store
from devops_agent.runtime import get_queue
from devops_agent.worker.handler import InvestigationHandler

configure_logging(settings.log_level)
log = get_logger("worker")


class Worker:
    def __init__(self) -> None:
        self.queue = get_queue()
        self.handler = InvestigationHandler(get_store(), get_idempotency())
        self._stop = False

    def stop(self, *_: object) -> None:
        self._stop = True

    def loop_forever(self) -> None:
        try:
            signal.signal(signal.SIGTERM, self.stop)
            signal.signal(signal.SIGINT, self.stop)
        except ValueError:
            pass
        log.info(
            "worker_started",
            concurrency=settings.worker_concurrency,
            queue=settings.queue_backend,
        )
        while not self._stop:
            try:
                messages = self.queue.receive(
                    max_messages=min(settings.worker_concurrency, 10),
                    wait_seconds=settings.sqs_wait_time_seconds if settings.queue_backend == "sqs" else 2,
                )
            except Exception:
                log.exception("receive_failed")
                time.sleep(2)
                continue
            if not messages:
                continue
            for msg in messages:
                try:
                    self.handler.handle(msg)
                    self.queue.delete(msg.receipt_handle)
                except Exception:
                    log.exception("handle_failed", message_id=msg.message_id)
                    if msg.approximate_receive_count >= 5:
                        log.error("poison_message", message_id=msg.message_id)
                        self.queue.delete(msg.receipt_handle)


def run() -> None:
    Worker().loop_forever()


if __name__ == "__main__":
    run()
