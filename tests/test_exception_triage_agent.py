from icshps.agents.triage import build_exception_triage_findings
from icshps.schemas import (
    CandidateRoutingDecision,
    FinalDecisionArtifact,
    RoutingCategory,
)


def test_exception_triage_agent_creates_manager_follow_up_findings() -> None:
    final_decision = FinalDecisionArtifact(
        run_id="run_001",
        bundle_id="bundle_001",
        scenario_type="strong_match",
        decisions=[
            CandidateRoutingDecision(
                candidate_id="candidate_001",
                application_id="app_001",
                routing_category=RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
                reason="High match. Human approval is required.",
                score=95.0,
                requires_human_approval=True,
            )
        ],
    )

    artifact = build_exception_triage_findings(final_decision=final_decision)

    assert artifact.run_id == "run_001"
    assert len(artifact.findings) == 1
    finding = artifact.findings[0]
    assert finding.source_agent == "exception_triage_agent_v1"
    assert finding.category == "triage"
    assert finding.title == "Interview routing follow-up"
    assert finding.requires_human_review is True
