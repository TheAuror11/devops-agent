from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.responses import Response

from devops_agent.api.routes import router
from devops_agent.config import settings
from devops_agent.observability import configure_logging, get_logger, new_correlation_id

configure_logging(settings.log_level)
log = get_logger("api")

WEB_DIST = Path(__file__).resolve().parents[3] / "apps" / "web" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if settings.seed_demo_data:
        from devops_agent.demo.seed import seed

        seed()
        log.info("demo_seeded")
    if settings.queue_backend == "local":
        from devops_agent.worker.embedded import start_embedded_worker

        start_embedded_worker()
        log.info("embedded_worker_started")
    yield


app = FastAPI(
    title="DevOps Agent",
    version="1.0.0",
    description="Autonomous AWS incident investigation — Bedrock tool-calling, RAG runbooks, MCP registry.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def correlation(request: Request, call_next):
    cid = request.headers.get("x-correlation-id") or new_correlation_id()
    response = await call_next(request)
    response.headers["x-correlation-id"] = cid
    return response


@app.exception_handler(Exception)
async def unhandled(_: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, HTTPException):
        raise exc
    log.exception("unhandled")
    return JSONResponse({"detail": "internal error"}, status_code=500)


app.include_router(router)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness — process is up. Used by ALB / ECS."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> JSONResponse:
    """Readiness — dependencies are reachable before taking traffic."""
    checks: dict[str, str] = {"api": "ok"}
    ok = True
    try:
        from devops_agent.persistence import get_store

        get_store().list_agent_spaces()
        checks["store"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["store"] = f"error:{exc}"
        ok = False
    try:
        from devops_agent.runtime import get_queue

        get_queue().attributes()
        checks["queue"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["queue"] = f"error:{exc}"
        ok = False
    status = 200 if ok else 503
    return JSONResponse({"status": "ready" if ok else "not_ready", "checks": checks}, status_code=status)


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        candidate = WEB_DIST / full_path
        if full_path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")


def run() -> None:
    import uvicorn

    uvicorn.run("devops_agent.api.app:app", host=settings.api_host, port=settings.api_port, reload=settings.is_local)
