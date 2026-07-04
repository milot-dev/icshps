from pathlib import Path

from icshps.agents.ats_mock import build_ats_payload
from icshps.schemas import (
    CandidateRoutingDecision,
    FinalDecisionArtifact,
    RoutingCategory,
)


def test_build_ats_payload_uses_local_mock_config(tmp_path: Path) -> None:
    export_path = tmp_path / "ats_export.json"
    requisition_path = tmp_path / "ats_requisition.json"
    export_path.write_text(
        """
{
  "mock_ats_system": "local_demo_ats",
  "requisition_id": "REQ-001",
  "notes": ["mock only"]
}
""",
        encoding="utf-8",
    )
    requisition_path.write_text(
        """{"requisition_id": "REQ-001", "job_id": "job_001"}""",
        encoding="utf-8",
    )

    payload = build_ats_payload(
        final_decision=final_decision(),
        ats_export_path=export_path,
        ats_requisition_path=requisition_path,
    )

    assert payload.dry_run is True
    assert payload.target_system == "local_demo_ats"
    assert payload.records[0].requisition_id == "REQ-001"
    assert payload.records[0].status == "review_candidate"
    assert "mock only" in payload.notes


def test_build_ats_payload_is_deterministic() -> None:
    first = build_ats_payload(final_decision=final_decision())
    second = build_ats_payload(final_decision=final_decision())

    assert first == second


def final_decision() -> FinalDecisionArtifact:
    return FinalDecisionArtifact(
        run_id="run_001",
        bundle_id="bundle_001",
        scenario_type="demo",
        decisions=[
            CandidateRoutingDecision(
                candidate_id="candidate_001",
                application_id="app_001",
                routing_category=RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
                reason="Eligible for interview review. Human approval is required.",
                score=91.0,
                blocking_finding_ids=[],
                requires_human_approval=True,
            )
        ],
        findings=[],
    )
