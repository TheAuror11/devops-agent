from __future__ import annotations

import json
import queue
import threading
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass
class QueueMessage:
    body: dict[str, Any]
    receipt_handle: str
    message_id: str
    approximate_receive_count: int = 1


class InvestigationQueue(Protocol):
    def enqueue(self, body: dict[str, Any], dedup_id: str | None = None) -> str: ...
    def receive(self, max_messages: int = 1, wait_seconds: int = 5) -> list[QueueMessage]: ...
    def delete(self, receipt_handle: str) -> None: ...
    def change_visibility(self, receipt_handle: str, seconds: int) -> None: ...


class InMemoryQueue:
    """Local stand-in for SQS. Used in APP_ENV=local and tests."""

    def __init__(self) -> None:
        self._q: queue.Queue[QueueMessage] = queue.Queue()
        self._inflight: dict[str, QueueMessage] = {}
        self._lock = threading.Lock()
        self._seq = 0

    def enqueue(self, body: dict[str, Any], dedup_id: str | None = None) -> str:
        with self._lock:
            self._seq += 1
            mid = dedup_id or f"msg_{self._seq}"
            msg = QueueMessage(body=body, receipt_handle=f"rh_{self._seq}", message_id=mid)
            self._q.put(msg)
            return mid

    def receive(self, max_messages: int = 1, wait_seconds: int = 5) -> list[QueueMessage]:
        out: list[QueueMessage] = []
        try:
            first = self._q.get(timeout=wait_seconds)
            out.append(first)
            self._inflight[first.receipt_handle] = first
        except queue.Empty:
            return []
        while len(out) < max_messages:
            try:
                msg = self._q.get_nowait()
                out.append(msg)
                self._inflight[msg.receipt_handle] = msg
            except queue.Empty:
                break
        return out

    def delete(self, receipt_handle: str) -> None:
        self._inflight.pop(receipt_handle, None)

    def change_visibility(self, receipt_handle: str, seconds: int) -> None:
        return None


class SqsQueue:
    def __init__(self, queue_url: str, client: Any = None) -> None:
        import boto3

        from devops_agent.config import settings

        self.queue_url = queue_url
        self.client = client or boto3.client("sqs", region_name=settings.aws_region)

    def enqueue(self, body: dict[str, Any], dedup_id: str | None = None) -> str:
        kwargs: dict[str, Any] = {
            "QueueUrl": self.queue_url,
            "MessageBody": json.dumps(body),
            "MessageAttributes": {
                "investigation_id": {
                    "DataType": "String",
                    "StringValue": str(body.get("investigation_id", "")),
                }
            },
        }
        if dedup_id:
            kwargs["MessageDeduplicationId"] = dedup_id
            kwargs["MessageGroupId"] = str(body.get("agent_space_id") or "default")
        resp = self.client.send_message(**kwargs)
        return resp["MessageId"]

    def receive(self, max_messages: int = 1, wait_seconds: int = 5) -> list[QueueMessage]:
        resp = self.client.receive_message(
            QueueUrl=self.queue_url,
            MaxNumberOfMessages=min(max_messages, 10),
            WaitTimeSeconds=wait_seconds,
            VisibilityTimeout=900,
            AttributeNames=["ApproximateReceiveCount"],
            MessageAttributeNames=["All"],
        )
        out: list[QueueMessage] = []
        for m in resp.get("Messages", []):
            out.append(
                QueueMessage(
                    body=json.loads(m["Body"]),
                    receipt_handle=m["ReceiptHandle"],
                    message_id=m["MessageId"],
                    approximate_receive_count=int(m.get("Attributes", {}).get("ApproximateReceiveCount", "1")),
                )
            )
        return out

    def delete(self, receipt_handle: str) -> None:
        self.client.delete_message(QueueUrl=self.queue_url, ReceiptHandle=receipt_handle)

    def change_visibility(self, receipt_handle: str, seconds: int) -> None:
        self.client.change_message_visibility(
            QueueUrl=self.queue_url, ReceiptHandle=receipt_handle, VisibilityTimeout=seconds
        )
