from pathlib import Path

from icshps.agents.verification import build_linkedin_consistency_findings
from icshps.schemas import CandidateProfile, EmploymentRecord, ExtractedField


def test_linkedin_date_contradiction_is_flagged(tmp_path: Path) -> None:
    linkedin_path = _linkedin_file(tmp_path)
    profile = _profile(
        employment=[
            EmploymentRecord(
                company="DataWorks",
                title="Backend Engineer",
                start_date="2021-01",
                end_date="2024-03",
                confidence=0.95,
            )
        ]
    )

    artifact = build_linkedin_consistency_findings(
        run_id="run_001",
        candidate_profile=profile,
        linkedin_profiles_path=linkedin_path,
    )

    finding = artifact.findings[0]
    assert finding.category == "linkedin_consistency"
    assert finding.severity == "warning"
    assert "contradict" in finding.title
    assert finding.evidence[0].source_type == "mock_linkedin_profile"


def test_linkedin_title_discrepancy_is_flagged(tmp_path: Path) -> None:
    linkedin_path = _linkedin_file(tmp_path, title="Engineering Manager")
    profile = _profile(
        employment=[
            EmploymentRecord(
                company="DataWorks",
                title="Backend Engineer",
                start_date="2022-06",
                end_date="2023-08",
                confidence=0.95,
            )
        ]
    )

    artifact = build_linkedin_consistency_findings(
        run_id="run_001",
        candidate_profile=profile,
        linkedin_profiles_path=linkedin_path,
    )

    assert any("title differs" in finding.title for finding in artifact.findings)


def test_reverse_chronology_is_flagged_without_external_data() -> None:
    profile = _profile(
        employment=[
            EmploymentRecord(company="Older Co", start_date="2020-01", end_date="2021-01"),
            EmploymentRecord(company="Newer Co", start_date="2022-01", end_date="2023-01"),
        ]
    )

    artifact = build_linkedin_consistency_findings(
        run_id="run_001",
        candidate_profile=profile,
        linkedin_profiles_path=None,
    )

    assert artifact.findings[0].title == "Employment history is not reverse chronological"


def _linkedin_file(tmp_path: Path, *, title: str = "Backend Engineer") -> Path:
    path = tmp_path / "linkedin_profiles.yaml"
    path.write_text(
        f"""
candidate_id: candidate_001
linkedin_profile:
  - company: DataWorks
    title: {title}
    start_date: 2022-06
    end_date: 2023-08
""",
        encoding="utf-8",
    )
    return path


def _profile(*, employment: list[EmploymentRecord]) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        employment_history=employment,
        extraction_confidence=0.97,
    )
