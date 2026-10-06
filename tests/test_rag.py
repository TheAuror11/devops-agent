from __future__ import annotations

from devops_agent.domain.models import Runbook
from devops_agent.rag.index import RunbookIndex


def test_retrieves_throttling_runbook() -> None:
    idx = RunbookIndex()
    idx.rebuild(
        [
            Runbook(
                agent_space_id="as1",
                title="DynamoDB throttling",
                path="ddb.md",
                content="connection pool waiters ProvisionedThroughputExceededException raise WCU",
                tags=["dynamodb", "pool"],
            ),
            Runbook(
                agent_space_id="as1",
                title="Lambda errors",
                path="lambda.md",
                content="function timeout stack trace alias rollback",
                tags=["lambda"],
            ),
        ]
    )
    hits = idx.search("checkout dynamodb connection pool throttle", k=2)
    assert hits
    assert "throttling" in hits[0].title.lower()
