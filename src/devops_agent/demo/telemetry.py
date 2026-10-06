from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

NOW = datetime(2026, 10, 6, 7, 42, tzinfo=UTC)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def incident_window() -> tuple[datetime, datetime]:
    return NOW - timedelta(minutes=45), NOW


class DemoTelemetry:
    """Deterministic AWS telemetry for the sample checkout retail platform.

    Mirrors the AWS DevOps Agent blog scenario: checkout latency caused by
    DynamoDB connection-pool saturation, with plausible competing hypotheses
    (config change, payment gateway slowness).
    """

    account_id = "123456789012"
    region = "us-east-1"
    space_name = "retail-checkout-prod"

    def alarms(self) -> list[dict[str, Any]]:
        return [
            {
                "AlarmName": "checkout-p95-latency",
                "StateValue": "ALARM",
                "StateUpdatedTimestamp": _iso(NOW - timedelta(minutes=16)),
                "MetricName": "Latency",
                "Namespace": "Checkout",
                "Threshold": 500,
                "Reason": "p95 latency 4200ms > 500ms for 3 datapoints",
            },
            {
                "AlarmName": "checkout-error-rate",
                "StateValue": "ALARM",
                "StateUpdatedTimestamp": _iso(NOW - timedelta(minutes=14)),
                "MetricName": "5xx",
                "Namespace": "Checkout",
                "Threshold": 1.0,
                "Reason": "error rate 6.8% > 1%",
            },
            {
                "AlarmName": "payments-latency",
                "StateValue": "ALARM",
                "StateUpdatedTimestamp": _iso(NOW - timedelta(minutes=11)),
                "MetricName": "Latency",
                "Namespace": "Payments",
                "Threshold": 800,
                "Reason": "p95 latency 1600ms — started AFTER checkout latency",
            },
            {
                "AlarmName": "catalog-cpu",
                "StateValue": "OK",
                "StateUpdatedTimestamp": _iso(NOW - timedelta(hours=6)),
                "MetricName": "CPUUtilization",
                "Namespace": "AWS/ECS",
                "Threshold": 80,
                "Reason": "OK",
            },
        ]

    def metrics(self, name: str, namespace: str = "", resource: str = "") -> dict[str, Any]:
        key = f"{namespace}:{name}:{resource}".lower()
        if "latency" in name.lower() and "checkout" in key:
            return {
                "metric": name,
                "unit": "Milliseconds",
                "datapoints": [
                    {"ts": _iso(NOW - timedelta(minutes=40)), "p50": 180, "p95": 260, "p99": 410},
                    {"ts": _iso(NOW - timedelta(minutes=25)), "p50": 190, "p95": 280, "p99": 430},
                    {"ts": _iso(NOW - timedelta(minutes=18)), "p50": 240, "p95": 1400, "p99": 3200},
                    {"ts": _iso(NOW - timedelta(minutes=10)), "p50": 210, "p95": 4200, "p99": 9100},
                    {"ts": _iso(NOW - timedelta(minutes=2)), "p50": 220, "p95": 4100, "p99": 8800},
                ],
                "baseline_p95": 280,
            }
        if "latency" in name.lower() and "payment" in key:
            return {
                "metric": name,
                "unit": "Milliseconds",
                "datapoints": [
                    {"ts": _iso(NOW - timedelta(minutes=40)), "p95": 220},
                    {"ts": _iso(NOW - timedelta(minutes=18)), "p95": 240},
                    {"ts": _iso(NOW - timedelta(minutes=12)), "p95": 900},
                    {"ts": _iso(NOW - timedelta(minutes=6)), "p95": 1600},
                ],
                "note": "Degradation began after checkout latency onset.",
            }
        if "throttle" in name.lower() or "dynamo" in key:
            return {
                "metric": name,
                "unit": "Count",
                "datapoints": [
                    {"ts": _iso(NOW - timedelta(minutes=40)), "throttles": 0, "consumed_wcu": 420},
                    {"ts": _iso(NOW - timedelta(minutes=18)), "throttles": 14, "consumed_wcu": 980},
                    {"ts": _iso(NOW - timedelta(minutes=10)), "throttles": 86, "consumed_wcu": 1400},
                ],
            }
        if "cpu" in name.lower():
            return {"metric": name, "datapoints": [{"ts": _iso(NOW), "avg": 31.0, "max": 44.0}]}
        return {"metric": name, "datapoints": [], "note": "no matching series"}

    def logs(self, log_group: str, filter_pattern: str = "", limit: int = 20) -> list[dict[str, Any]]:
        checkout_errors = [
            {
                "timestamp": _iso(NOW - timedelta(minutes=17)),
                "message": "ERROR checkout Unable to acquire DynamoDB connection from pool after 200ms (active=47/50 idle=0 waiters=23)",
            },
            {
                "timestamp": _iso(NOW - timedelta(minutes=16)),
                "message": "WARN checkout Retrying PutItem Orders table — ProvisionedThroughputExceededException",
            },
            {
                "timestamp": _iso(NOW - timedelta(minutes=12)),
                "message": "ERROR checkout POST /orders 504 upstream timeout after 8000ms request_id=b7e1",
            },
            {
                "timestamp": _iso(NOW - timedelta(minutes=9)),
                "message": "INFO checkout payment gateway slow TTFB=1400ms — called after local pool wait",
            },
        ]
        if "checkout" in log_group.lower() or "orders" in log_group.lower():
            return checkout_errors[:limit]
        if "lambda" in log_group.lower():
            return [
                {
                    "timestamp": _iso(NOW - timedelta(minutes=5)),
                    "message": "ERROR Intentional test exception raised by FaultyDemoFunction",
                }
            ]
        return [
            {"timestamp": _iso(NOW - timedelta(minutes=3)), "message": f"INFO {log_group} heartbeat ok"}
        ]

    def traces(self, service: str) -> list[dict[str, Any]]:
        return [
            {
                "trace_id": "1-68e3aa00-checkout0001",
                "duration_ms": 8120,
                "segments": [
                    {"name": "alb/checkout", "ms": 12},
                    {"name": "ecs:checkout", "ms": 7900, "annotation": "pool_wait_ms=6100"},
                    {"name": "dynamodb:Orders", "ms": 180, "throttle": True},
                    {"name": "payments", "ms": 1400, "note": "started after pool wait"},
                ],
            }
        ]

    def cloudtrail(self, resource: str = "") -> list[dict[str, Any]]:
        return [
            {
                "eventTime": _iso(NOW - timedelta(minutes=22)),
                "eventName": "UpdateFunctionConfiguration",
                "user": "sre-oncall",
                "resource": "checkout-api",
                "detail": "LOG_LEVEL=DEBUG — logging verbosity only",
            },
            {
                "eventTime": _iso(NOW - timedelta(hours=14)),
                "eventName": "UpdateTable",
                "resource": "Orders",
                "detail": "billingMode remains PROVISIONED, WCU=800",
            },
        ]

    def deployments(self, service: str = "") -> list[dict[str, Any]]:
        return [
            {
                "pipeline": "checkout-cd",
                "sha": "9f3c1a2",
                "message": "increase checkout DynamoDB client pool from 20 to 50 and enable batch writes",
                "deployed_at": _iso(NOW - timedelta(hours=1, minutes=6)),
                "author": "payments-platform",
                "status": "SUCCESS",
            },
            {
                "pipeline": "checkout-cd",
                "sha": "41ab90e",
                "message": "add request id to access logs",
                "deployed_at": _iso(NOW - timedelta(days=2)),
                "status": "SUCCESS",
            },
        ]

    def lambda_config(self, name: str) -> dict[str, Any]:
        return {
            "FunctionName": name,
            "Runtime": "python3.12",
            "Timeout": 8,
            "MemorySize": 256,
            "LastModified": _iso(NOW - timedelta(days=3)),
            "Environment": {"LOG_LEVEL": "DEBUG"},
        }

    def ecs_service(self, name: str) -> dict[str, Any]:
        return {
            "serviceName": name,
            "runningCount": 6,
            "desiredCount": 6,
            "cpu": "512",
            "memory": "1024",
            "deployments": [{"status": "PRIMARY", "runningCount": 6, "createdAt": _iso(NOW - timedelta(hours=1))}],
        }

    def dynamodb_table(self, name: str) -> dict[str, Any]:
        return {
            "TableName": name,
            "BillingMode": "PROVISIONED",
            "ProvisionedThroughput": {"ReadCapacityUnits": 400, "WriteCapacityUnits": 800},
            "ItemCount": 18_400_000,
            "ConsumedWriteCapacity": {"avg": 1380, "provisioned": 800},
            "ClientPool": {"size": 50, "active": 47, "waiters": 23},
        }

    def describe_resource(self, kind: str, name: str) -> dict[str, Any]:
        if kind in {"lambda", "function"}:
            return self.lambda_config(name)
        if kind in {"ecs", "service"}:
            return self.ecs_service(name)
        if kind in {"dynamodb", "table"}:
            return self.dynamodb_table(name)
        return {"kind": kind, "name": name, "note": "unknown"}


telemetry = DemoTelemetry()
