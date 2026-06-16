from pathlib import Path

from icshps.agents.verification import build_mandatory_certification_findings
from icshps.schemas.profile import CandidateProfile, CertificationRecord, ExtractedField


def test_mandatory_certification_check_flags_missing_required_cert(tmp_path: Path) -> None:
    skills_matrix = tmp_path / "skills_matrix.yaml"
    skills_matrix.write_text(
        """
mandatory_certifications:
  - name: AWS Certified Solutions Architect
    missing_severity: blocking
""",
        encoding="utf-8",
    )
    profile = CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        certifications=[],
        extraction_confidence=1.0,
    )

    artifact = build_mandatory_certification_findings(
        run_id="run_001",
        candidate_profile=profile,
        skills_matrix_path=skills_matrix,
    )

    finding = artifact.findings[0]
    assert finding.severity == "blocking"
    assert finding.candidate_id == "candidate_001"
    assert finding.requires_human_review is True
    assert "does not include" in finding.reason


def test_mandatory_certification_check_marks_present_cert_as_info(tmp_path: Path) -> None:
    skills_matrix = tmp_path / "skills_matrix.yaml"
    skills_matrix.write_text("mandatory_certifications:\n  - Kubernetes Administrator\n", encoding="utf-8")
    profile = CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        certifications=[
            CertificationRecord(name="Kubernetes Administrator", confidence=1.0)
        ],
        extraction_confidence=1.0,
    )

    artifact = build_mandatory_certification_findings(
        run_id="run_001",
        candidate_profile=profile,
        skills_matrix_path=skills_matrix,
    )

    assert artifact.findings[0].severity == "info"
    assert artifact.findings[0].requires_human_review is False
