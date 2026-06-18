from pathlib import Path

from icshps.agents.anomaly import build_anomaly_findings
from icshps.schemas import CandidateProfile, EmploymentRecord, ExtractedField


def test_duplicate_candidate_applications_are_detected() -> None:
    artifact = build_anomaly_findings(
        run_id="run_001",
        candidate_profiles=[
            _profile("candidate_a", "app_a", email="same@example.com"),
            _profile("candidate_b", "app_b", email="same@example.com"),
        ],
    )

    finding = artifact.findings[0]
    assert finding.title == "Duplicate candidate applications detected"
    assert finding.category == "anomaly"
    assert finding.severity == "warning"


def test_same_candidate_three_roles_is_detected(tmp_path: Path) -> None:
    history_path = tmp_path / "application_history.yaml"
    history_path.write_text(
        """
candidate_id: candidate_multi_role_001
applications:
  - application_id: app_backend
    role_id: job_backend
  - application_id: app_ml
    role_id: job_ml
  - application_id: app_data
    role_id: job_data
""",
        encoding="utf-8",
    )

    artifact = build_anomaly_findings(
        run_id="run_001",
        candidate_profiles=[],
        application_history_path=history_path,
    )

    finding = artifact.findings[0]
    assert finding.title == "Candidate applied to multiple roles"
    assert finding.candidate_id == "candidate_multi_role_001"
    assert "duplicate / multi-role review" in finding.recommendation


def test_overlapping_resume_employment_dates_are_flagged() -> None:
    profile = _profile(
        "candidate_001",
        "app_001",
        employment=[
            EmploymentRecord(company="Alpha", start_date="2021-01", end_date="2022-12"),
            EmploymentRecord(company="Beta", start_date="2022-06", end_date="2023-02"),
        ],
    )

    artifact = build_anomaly_findings(
        run_id="run_001",
        candidate_profiles=[profile],
    )

    assert artifact.findings[0].title == "Overlapping employment history detected"
    assert "manual review" in artifact.findings[0].reason


def _profile(
    candidate_id: str,
    application_id: str,
    *,
    email: str | None = None,
    employment: list[EmploymentRecord] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        email=ExtractedField(value=email, confidence=1.0) if email else None,
        employment_history=employment or [],
        extraction_confidence=0.95,
    )
