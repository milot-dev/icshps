from pathlib import Path

from icshps.agents.verification import build_credential_verification_findings
from icshps.schemas.profile import (
    CandidateProfile,
    CertificationRecord,
    EducationRecord,
    ExtractedField,
)


def test_credential_verification_flags_international_degree_pending() -> None:
    profile = build_profile(
        education=[
            EducationRecord(
                institution="University of Example",
                degree="Bachelor",
                country="Germany",
                is_international=True,
                confidence=0.9,
            )
        ],
        certifications=[],
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
    )

    finding = artifact.findings[0]
    assert finding.category == "credential"
    assert finding.severity == "warning"
    assert finding.candidate_id == "candidate_001"
    assert "International degree" in finding.title


def test_credential_verification_uses_mock_verified_evidence(tmp_path: Path) -> None:
    evidence_path = tmp_path / "credential_evidence.yaml"
    evidence_path.write_text(
        """
education_registry:
  - institution: University of Example
    degree: Bachelor
    status: verified
certification_registry:
  - name: AWS Certified Developer
    issuer: AWS
    status: verified
""",
        encoding="utf-8",
    )
    profile = build_profile(
        education=[
            EducationRecord(
                institution="University of Example",
                degree="Bachelor",
                confidence=0.9,
            )
        ],
        certifications=[
            CertificationRecord(
                name="AWS Certified Developer",
                issuer="AWS",
                confidence=0.9,
            )
        ],
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
        credential_evidence_path=evidence_path,
    )

    assert [finding.severity for finding in artifact.findings] == ["info", "info"]
    assert all(not finding.requires_human_review for finding in artifact.findings)


def test_credential_verification_flags_low_confidence_certification() -> None:
    profile = build_profile(
        education=[],
        certifications=[
            CertificationRecord(name="Handwritten Safety License", confidence=0.4)
        ],
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
    )

    finding = artifact.findings[0]
    assert finding.severity == "warning"
    assert "manual credential review" in finding.recommendation.lower()


def build_profile(
    *,
    education: list[EducationRecord],
    certifications: list[CertificationRecord],
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Example Candidate", confidence=1.0),
        education=education,
        certifications=certifications,
        extraction_confidence=1.0,
    )
