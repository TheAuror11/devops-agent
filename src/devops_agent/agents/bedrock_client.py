from __future__ import annotations

from typing import Any

from devops_agent.config import settings
from devops_agent.observability import BEDROCK_CALLS, get_logger

log = get_logger("bedrock")


class BedrockConverse:
    def __init__(self, model_id: str | None = None, region: str | None = None) -> None:
        self.model_id = model_id or settings.bedrock_model_id
        self.region = region or settings.bedrock_region
        self._client = None

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("bedrock-runtime", region_name=self.region)
        return self._client

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": messages,
            "system": [{"text": system}],
            "inferenceConfig": {
                "maxTokens": settings.bedrock_max_tokens,
                "temperature": settings.bedrock_temperature,
            },
        }
        if tools:
            kwargs["toolConfig"] = {"tools": tools, "toolChoice": {"auto": {}}}
        resp = self.client.converse(**kwargs)
        BEDROCK_CALLS.labels(stop_reason=resp.get("stopReason", "unknown")).inc()
        log.info("bedrock_converse", stop_reason=resp.get("stopReason"), model=self.model_id)
        return resp
