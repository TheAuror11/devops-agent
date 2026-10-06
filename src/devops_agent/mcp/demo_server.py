from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Demo MCP Server", version="1.0.0")


class RpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: int | str = 1
    method: str
    params: dict[str, Any] | None = None


TOOLS = [
    {
        "name": "query_apm_latency",
        "description": "Query application latency percentiles from the org APM (Grafana/Prometheus stand-in).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "service": {"type": "string"},
                "window_minutes": {"type": "integer", "default": 30},
            },
            "required": ["service"],
        },
    },
    {
        "name": "query_error_budget",
        "description": "Fetch remaining SLO error budget for a service.",
        "inputSchema": {
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
        },
    },
]


def _apm(service: str, window: int) -> dict[str, Any]:
    if "checkout" in service.lower():
        return {
            "service": service,
            "window_minutes": window,
            "p50_ms": 210,
            "p95_ms": 4200,
            "p99_ms": 9100,
            "baseline_p95_ms": 280,
            "anomaly": True,
            "note": "Latency cliff started ~18 minutes ago, concentrated on POST /orders.",
        }
    return {
        "service": service,
        "window_minutes": window,
        "p50_ms": 40,
        "p95_ms": 120,
        "p99_ms": 240,
        "baseline_p95_ms": 110,
        "anomaly": False,
    }


def _budget(service: str) -> dict[str, Any]:
    if "checkout" in service.lower():
        return {"service": service, "slo": "99.9%", "budget_remaining_pct": 12.0, "burn_rate_1h": 8.4}
    return {"service": service, "slo": "99.9%", "budget_remaining_pct": 87.0, "burn_rate_1h": 0.4}


@app.post("/mcp")
def rpc(req: RpcRequest) -> dict[str, Any]:
    if req.method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req.id,
            "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "demo-apm", "version": "1.0.0"}},
        }
    if req.method == "tools/list":
        return {"jsonrpc": "2.0", "id": req.id, "result": {"tools": TOOLS}}
    if req.method == "tools/call":
        params = req.params or {}
        name = params.get("name")
        args = params.get("arguments") or {}
        if name == "query_apm_latency":
            result = _apm(args.get("service", "unknown"), int(args.get("window_minutes", 30)))
        elif name == "query_error_budget":
            result = _budget(args.get("service", "unknown"))
        else:
            return {"jsonrpc": "2.0", "id": req.id, "error": {"code": -32601, "message": f"unknown tool {name}"}}
        return {"jsonrpc": "2.0", "id": req.id, "result": {"content": [{"type": "json", "json": result}]}}
    return {"jsonrpc": "2.0", "id": req.id, "error": {"code": -32601, "message": "method not found"}}


def run() -> None:
    import uvicorn

    uvicorn.run("devops_agent.mcp.demo_server:app", host="0.0.0.0", port=8090, reload=False)
