from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: Literal["local", "test", "prod"] = "local"
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
    api_cors_origins: str = "http://localhost:5173,http://localhost:8080"
    api_keys: str = "dev-local-key"

    aws_region: str = "us-east-1"
    aws_account_id: str = "000000000000"

    bedrock_model_id: str = ""
    bedrock_embedding_model_id: str = "amazon.titan-embed-text-v2:0"
    bedrock_region: str = "us-east-1"
    bedrock_max_tokens: int = 4096
    bedrock_temperature: float = 0.1
    bedrock_max_tool_rounds: int = 12
    bedrock_max_inflight_per_task: int = 2
    bedrock_slot_timeout_seconds: float = 120.0
    bedrock_max_retries: int = 4

    store_backend: Literal["local", "dynamodb"] = "local"
    data_dir: str = "./data"

    queue_backend: Literal["local", "sqs"] = "local"
    sqs_investigation_queue_url: str = ""
    sqs_dlq_url: str = ""
    sqs_wait_time_seconds: int = 20
    sqs_is_fifo: bool = False
    sqs_visibility_timeout_seconds: int = 900
    worker_concurrency: int = 4
    visibility_heartbeat_seconds: int = 300
    graceful_shutdown_seconds: int = 120

    # Ingress backpressure (0 = disabled)
    max_queue_depth: int = 500
    max_queue_age_seconds: int = 900
    max_investigations_per_minute: int = 120

    tool_max_inflight_per_task: int = 8

    ddb_table_prefix: str = "devops-agent"
    opensearch_endpoint: str = ""
    opensearch_index: str = "devops-agent-runbooks"

    idempotency_ttl_seconds: int = 86400
    circuit_breaker_failure_threshold: int = 5
    circuit_breaker_reset_seconds: int = 30

    jwt_secret: str = "change-me-in-production"
    jwt_issuer: str = "devops-agent"

    seed_demo_data: bool = True

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.api_cors_origins.split(",") if o.strip()]

    @property
    def api_key_set(self) -> set[str]:
        return {k.strip() for k in self.api_keys.split(",") if k.strip()}

    @property
    def use_bedrock(self) -> bool:
        return bool(self.bedrock_model_id.strip())

    @property
    def is_local(self) -> bool:
        return self.app_env in {"local", "test"}

    @property
    def table(self) -> str:
        return self.ddb_table_prefix


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
