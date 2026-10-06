from __future__ import annotations

import time

from fastapi.testclient import TestClient

from devops_agent.api.app import app


def test_health_and_seeded_space() -> None:
    with TestClient(app) as client:
        h = client.get("/v1/health")
        assert h.status_code == 200
        spaces = client.get("/v1/agent-spaces")
        assert spaces.status_code == 200
        assert any(s["name"] == "retail-checkout-prod" for s in spaces.json())


def test_investigation_lifecycle() -> None:
    with TestClient(app) as client:
        spaces = client.get("/v1/agent-spaces").json()
        space_id = spaces[0]["id"]
        created = client.post(
            "/v1/investigations",
            json={
                "agent_space_id": space_id,
                "title": "Checkout p95 latency cliff",
                "description": "Orders timing out, payment latency followed.",
                "priority": "HIGH",
                "starting_point": "Latest alarm",
                "idempotency_key": "test-checkout-1",
            },
        )
        assert created.status_code == 202
        inv_id = created.json()["id"]
        dup = client.post(
            "/v1/investigations",
            json={
                "agent_space_id": space_id,
                "title": "Checkout p95 latency cliff",
                "description": "Orders timing out, payment latency followed.",
                "priority": "HIGH",
                "idempotency_key": "test-checkout-1",
            },
        )
        assert dup.json()["id"] == inv_id

        terminal = {"COMPLETED", "FAILED"}
        inv = created.json()
        for _ in range(90):
            inv = client.get(f"/v1/investigations/{inv_id}").json()
            if inv["status"] in terminal:
                break
            time.sleep(0.4)
        assert inv["status"] == "COMPLETED", inv
        assert inv["root_cause"]
        assert inv["hypotheses"]
        journal = client.get(f"/v1/investigations/{inv_id}/journal").json()
        types = {j["record_type"] for j in journal}
        assert "triage_summary" in types
        assert "root_cause" in types
        assert "mitigation_plan" in types
        recs = client.get("/v1/recommendations").json()
        assert recs
