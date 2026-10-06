from __future__ import annotations

import threading

from devops_agent.observability import get_logger
from devops_agent.worker.main import Worker

log = get_logger("embedded_worker")
_started = False


def start_embedded_worker() -> None:
    global _started
    if _started:
        return
    _started = True

    def _run() -> None:
        worker = Worker()
        log.info("embedded_worker_loop")
        worker.loop_forever()

    t = threading.Thread(target=_run, name="embedded-investigation-worker", daemon=True)
    t.start()
