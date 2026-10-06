.PHONY: install install-web dev api worker web test lint fmt seed docker-up docker-down demo

VENV ?= .venv
PY := $(VENV)/bin/python
PIP := $(VENV)/bin/pip

install:
	python3 -m venv $(VENV)
	$(PIP) install -U pip
	$(PIP) install -e ".[dev]"

install-web:
	cd apps/web && npm install

dev: api

api:
	APP_ENV=local $(VENV)/bin/uvicorn devops_agent.api.app:app --reload --host 0.0.0.0 --port 8080

worker:
	APP_ENV=local $(VENV)/bin/python -m devops_agent.worker.main

web:
	cd apps/web && npm run dev

seed:
	APP_ENV=local $(VENV)/bin/python -m devops_agent.demo.seed

test:
	$(VENV)/bin/pytest -q

lint:
	$(VENV)/bin/ruff check src tests
	$(VENV)/bin/mypy src

fmt:
	$(VENV)/bin/ruff format src tests

demo: seed
	@echo "API:  http://localhost:8080"
	@echo "UI:   http://localhost:5173"
	@echo "Docs: http://localhost:8080/docs"

docker-up:
	docker compose up --build

docker-down:
	docker compose down -v
