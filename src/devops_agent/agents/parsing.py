from __future__ import annotations

import re

from devops_agent.domain.models import (
    Hypothesis,
    HypothesisStatus,
    Investigation,
    MitigationPlan,
    Recommendation,
)


def parse_root_cause(text: str) -> str | None:
    m = re.search(r"ROOT_CAUSE:\s*(.+)", text, re.I | re.S)
    if not m:
        return None
    return m.group(1).split("HYPOTHESES:")[0].strip()[:2000]


def parse_hypotheses(text: str) -> list[Hypothesis]:
    block = text.split("HYPOTHESES:")[-1] if "HYPOTHESES:" in text.upper() or "HYPOTHESES:" in text else text
    hyps: list[Hypothesis] = []
    for line in block.splitlines():
        line = line.strip(" -*\t")
        if "|" not in line:
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        title = parts[0]
        status_raw = parts[1].replace(" ", "_").upper()
        try:
            status = HypothesisStatus(status_raw)
        except ValueError:
            mapped = {
                "ROOT CAUSE": HypothesisStatus.ROOT_CAUSE,
                "ROOT_CAUSE": HypothesisStatus.ROOT_CAUSE,
                "CAUSE": HypothesisStatus.CAUSE,
                "REFUTED": HypothesisStatus.REFUTED,
                "CANDIDATE": HypothesisStatus.CANDIDATE,
            }
            status = mapped.get(parts[1].upper(), HypothesisStatus.CANDIDATE)
        conf = 0.0
        if len(parts) >= 3:
            try:
                conf = float(parts[2])
            except ValueError:
                conf = 0.0
        statement = parts[3] if len(parts) > 3 else title
        if len(title) > 120:
            continue
        hyps.append(Hypothesis(title=title, statement=statement, status=status, confidence=conf))
    return hyps[:8]


def parse_mitigation(text: str) -> MitigationPlan:
    def section(name: str) -> list[str]:
        m = re.search(rf"{name}:?\s*(.+?)(?:\n[A-Z][a-zA-Z ]+:|\Z)", text, re.I | re.S)
        if not m:
            return []
        body = m.group(1)
        return [re.sub(r"^\d+\.\s*", "", ln).strip(" -") for ln in body.splitlines() if ln.strip()][:12]

    steps = section("Steps") or [
        ln.strip(" -") for ln in text.splitlines() if ln.strip().startswith(("1.", "2.", "3."))
    ]
    default_strategy = "Restore service with reversible capacity and client changes."
    strategy = next(
        (ln.strip() for ln in text.splitlines() if ln.lower().startswith("strategy")),
        default_strategy,
    )[:500]
    return MitigationPlan(
        strategy=strategy,
        steps=steps or ["Review plan with on-call before applying any write."],
        validation_checks=section("Validation checks") or section("Validation"),
        success_criteria=section("Success criteria"),
        rollback=section("Rollback"),
        blast_radius=" ".join(section("Blast radius")) or "See topology walk.",
    )


def parse_recommendations(text: str, inv: Investigation) -> list[Recommendation]:
    recs: list[Recommendation] = []
    for line in text.splitlines():
        if "|" not in line:
            continue
        parts = [p.strip() for p in re.sub(r"^\d+\s*\|", "", line).split("|")]
        if len(parts) < 3:
            continue
        category, title, rationale = parts[0], parts[1], parts[2]
        if category.lower() in {"category", "observability"} or len(title) > 8:
            effort = parts[3] if len(parts) > 3 else "medium"
            impact = parts[4] if len(parts) > 4 else "high"
            if effort not in {"low", "medium", "high"}:
                effort = "medium"
            if impact not in {"low", "medium", "high"}:
                impact = "high"
            recs.append(
                Recommendation(
                    agent_space_id=inv.agent_space_id,
                    investigation_id=inv.id,
                    category=category[:40],
                    title=title[:160],
                    rationale=rationale[:500],
                    effort=effort,  # type: ignore[arg-type]
                    impact=impact,  # type: ignore[arg-type]
                )
            )
    return recs[:10]
