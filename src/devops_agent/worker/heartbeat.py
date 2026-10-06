from __future__ import annotations

import threading
from collections.abc import Callable

from devops_agent.config import settings
from devops_agent.observability import get_logger

log = get_logger("heartbeat")


class VisibilityHeartbeat:
    """Extends SQS visibility while a long investigation runs (prevents duplicate delivery)."""

    def __init__(
        self,
        receipt_handle: str,
        extend: Callable[[str, int], None],
        interval_seconds: int | None = None,
        visibility_seconds: int | None = None,
    ) -> None:
        self.receipt_handle = receipt_handle
        self.extend = extend
        self.interval = interval_seconds or settings.visibility_heartbeat_seconds
        self.visibility = visibility_seconds or settings.sqs_visibility_timeout_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self.interval <= 0:
            return
        self._thread = threading.Thread(target=self._run, name="sqs-visibility-heartbeat", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def _run(self) -> None:
        while not self._stop.wait(self.interval):
            try:
                self.extend(self.receipt_handle, self.visibility)
                log.debug("visibility_extended", seconds=self.visibility)
            except Exception:
                log.exception("visibility_extend_failed")
