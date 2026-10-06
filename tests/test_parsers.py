from __future__ import annotations

from devops_agent.agents.orchestrator import parse_hypotheses, parse_root_cause
from devops_agent.domain.models import HypothesisStatus


def test_parse_root_cause_and_hypotheses() -> None:
    text = """
Some preamble
ROOT_CAUSE: The pool is saturated.

HYPOTHESES:
- DynamoDB pool/WCU saturation | ROOT_CAUSE | 0.91 | pool wait
- Payment gateway degradation | CAUSE | 0.35 | symptom
- Debug logging config change | REFUTED | 0.08 | cannot affect latency
"""
    rc = parse_root_cause(text)
    assert rc and "pool is saturated" in rc
    hyps = parse_hypotheses(text)
    assert len(hyps) == 3
    assert hyps[0].status == HypothesisStatus.ROOT_CAUSE
    assert hyps[2].status == HypothesisStatus.REFUTED
