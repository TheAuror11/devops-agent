FROM python:3.12-slim AS base
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md ./
COPY src ./src
COPY runbooks ./runbooks
RUN pip install --no-cache-dir -e .

FROM base AS api
ENV APP_ENV=prod API_HOST=0.0.0.0 API_PORT=8080
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD curl -f http://127.0.0.1:8080/healthz || exit 1
CMD ["uvicorn", "devops_agent.api.app:app", "--host", "0.0.0.0", "--port", "8080"]

FROM base AS worker
ENV APP_ENV=prod
CMD ["python", "-m", "devops_agent.worker.main"]

FROM base AS mcp
EXPOSE 8090
CMD ["uvicorn", "devops_agent.mcp.demo_server:app", "--host", "0.0.0.0", "--port", "8090"]
