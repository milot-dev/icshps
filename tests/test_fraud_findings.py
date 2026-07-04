from pathlib import Path

from icshps.agents.anomaly import build_fraud_findings
from icshps.agents.orchestrator.routing_agent import build_final_decision_artifact
from icshps.schemas import (
    BundleContext,
    BundleInfo,
    CandidateApplication,
    CandidateProfile,
    ExtractedField,
    FindingCategory,
    FindingsArtifact,
    JobInfo,
    OptionalInputPaths,
    RequiredInputPaths,
    RoutingCategory,
    ScenarioInfo,
)


def test_fraud_findings_detect_identity_collision() -> None:
    artifact = build_fraud_findings(
        run_id="run_001",
        candidate_profiles=[
            profile("candidate_001", "app_001", email="shared@example.test"),
            profile("candidate_002", "app_002", email="shared@example.test"),
        ],
    )

    assert artifact.findings
    assert artifact.findings[0].category == FindingCategory.FRAUD
    assert artifact.findings[0].requires_human_review is True


def test_fraud_findings_load_json_signal_contract(tmp_path: Path) -> None:
    signals_path = tmp_path / "fraud_signals.json"
    signals_path.write_text(
        """
{
  "signals": [
    {
      "candidate_id": "candidate_001",
      "application_id": "app_001",
      "signal": "credential_issuer_mismatch",
      "description": "Mock issuer does not match resume claim.",
      "confidence": 0.82
    }
  ]
}
""",
        encoding="utf-8",
    )

    artifact = build_fraud_findings(
        run_id="run_001",
        candidate_profiles=[],
        fraud_signals_path=signals_path,
    )

    assert artifact.findings[0].id == "fraud-mock-signal-001"
    assert artifact.findings[0].evidence[0].source_type == "mock_fraud_signals"


def test_fraud_findings_route_to_manual_review() -> None:
    fraud_artifact = FindingsArtifact(
        run_id="run_001",
        findings=build_fraud_findings(
            run_id="run_001",
            candidate_profiles=[
                profile("candidate_001", "app_001", email="shared@example.test"),
                profile("candidate_002", "app_002", email="shared@example.test"),
            ],
        ).findings,
    )

    final_decision = build_final_decision_artifact(
        context=context(),
        candidate_profiles=[
            profile("candidate_001", "app_001", email="shared@example.test"),
            profile("candidate_002", "app_002", email="shared@example.test"),
        ],
        fraud_findings=fraud_artifact,
    )

    assert final_decision.decisions[0].routing_category == RoutingCategory.MANUAL_REVIEW
    assert final_decision.decisions[0].blocking_finding_ids


def profile(candidate_id: str, application_id: str, *, email: str) -> CandidateProfile:
    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value=candidate_id, confidence=1.0),
        email=ExtractedField(value=email, confidence=1.0),
        extraction_confidence=0.95,
    )


def context() -> BundleContext:
    return BundleContext(
        run_id="run_001",
        bundle_path=Path("bundle"),
        bundle=BundleInfo(id="bundle_001", name="Bundle 001"),
        scenario=ScenarioInfo(id="scenario_001", type="fraud_demo"),
        job=JobInfo(id="job_001", title="AI Backend Engineer"),
        candidates=[
            CandidateApplication(
                id="candidate_001",
                application_id="app_001",
                name="Candidate 001",
                target_job_id="job_001",
                resume_file=Path("resume.pdf"),
            )
        ],
        required_inputs=RequiredInputPaths(
            job_description=Path("job_description.md"),
            skills_matrix=Path("skills_matrix.yaml"),
            eeo_policy=Path("eeo_policy.yaml"),
            credential_rules=Path("credential_rules.yaml"),
            hris_master=Path("hris_master.yaml"),
        ),
        optional_inputs=OptionalInputPaths(),
        is_ready=True,
    )
