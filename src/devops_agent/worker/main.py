from __future__ import annotations

import signal
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from devops_agent.api.deps import get_idempotency
from devops_agent.config import settings
from devops_agent.observability import configure_logging, get_logger
from devops_agent.persistence import get_store
from devops_agent.runtime import get_queue
from devops_agent.worker.handler import InvestigationHandler

configure_logging(settings.log_level)
log = get_logger("worker")


class Worker:
    """Horizontally scalable investigation consumer.

    True concurrency = ThreadPoolExecutor(worker_concurrency) × ECS desired count.
    Visibility heartbeats prevent duplicate delivery on long Bedrock investigations.
    """

    def __init__(self) -> None:
        self.queue = get_queue()
        self.handler = InvestigationHandler(get_store(), get_idempotency(), queue=self.queue)
        self._stop = False
        self._pool = ThreadPoolExecutor(
            max_workers=max(settings.worker_concurrency, 1),
            thread_name_prefix="inv-worker",
        )

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
            heartbeat_s=settings.visibility_heartbeat_seconds,
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

            futures = {self._pool.submit(self._process, msg): msg for msg in messages}
            for fut in as_completed(futures):
                msg = futures[fut]
                try:
                    fut.result()
                except Exception:
                    log.exception("handle_failed", message_id=msg.message_id)

        log.info("worker_draining", timeout_s=settings.graceful_shutdown_seconds)
        self._pool.shutdown(wait=True, cancel_futures=False)

    def _process(self, msg) -> None:
        try:
            self.handler.handle(msg)
            self.queue.delete(msg.receipt_handle)
        except Exception:
            log.exception("handle_failed", message_id=msg.message_id)
            # Do not delete — let visibility expire so SQS can redrive to DLQ.
            if msg.approximate_receive_count >= 5:
                log.error("poison_message_will_dlq", message_id=msg.message_id)
                try:
                    self.queue.change_visibility(msg.receipt_handle, 0)
                except Exception:
                    log.exception("force_visibility_zero_failed")


def run() -> None:
    Worker().loop_forever()


if __name__ == "__main__":
    run()
