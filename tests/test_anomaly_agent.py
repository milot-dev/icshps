from pathlib import Path

from icshps.agents.anomaly import build_anomaly_findings
from icshps.schemas.profile import CandidateProfile, EmploymentRecord, ExtractedField


def test_anomaly_agent_detects_duplicate_email_and_employment_overlap() -> None:
    profiles = [
        build_profile(
            candidate_id="candidate_001",
            application_id="app_001",
            email="same@example.com",
            employment_history=[
                EmploymentRecord(
                    company="Company A",
                    start_date="2023-01",
                    end_date="2023-12",
                ),
                EmploymentRecord(
                    company="Company B",
                    start_date="2023-06",
                    end_date="2024-01",
                ),
            ],
        ),
        build_profile(
            candidate_id="candidate_002",
            application_id="app_002",
            email="same@example.com",
            employment_history=[],
        ),
    ]

    artifact = build_anomaly_findings(run_id="run_001", candidate_profiles=profiles)

    assert [finding.id for finding in artifact.findings] == [
        "anomaly-duplicate-email-001",
        "anomaly-employment-overlap-002",
    ]


def test_anomaly_agent_detects_multi_role_applications(tmp_path: Path) -> None:
    history_path = tmp_path / "application_history.yaml"
    history_path.write_text(
        """
applications:
  - candidate_id: candidate_001
    job_id: job_a
  - candidate_id: candidate_001
    job_id: job_b
  - candidate_id: candidate_001
    job_id: job_c
""",
        encoding="utf-8",
    )

    artifact = build_anomaly_findings(
        run_id="run_001",
        candidate_profiles=[],
        application_history_path=history_path,
    )

    assert [finding.id for finding in artifact.findings] == ["anomaly-multi-role-001"]


def build_profile(
    *,
    candidate_id: str,
    application_id: str,
    email: str,
    employment_history: list[EmploymentRecord],
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Example Candidate", confidence=1.0),
        email=ExtractedField(value=email, confidence=1.0),
        employment_history=employment_history,
        extraction_confidence=1.0,
    )
