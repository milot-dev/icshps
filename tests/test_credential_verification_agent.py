from pathlib import Path

from icshps.agents.verification import build_credential_verification_findings
from icshps.schemas import (
    CandidateProfile,
    CertificationRecord,
    EducationRecord,
    ExtractedField,
)


def test_international_degree_without_mock_match_is_pending() -> None:
    profile = _profile(
        education=[
            EducationRecord(
                institution="International Technical University",
                degree="MSc Computer Science",
                country="Non-local jurisdiction",
                is_international=True,
                confidence=0.91,
            )
        ],
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
    )

    assert artifact.findings[0].category == "credential"
    assert artifact.findings[0].severity == "warning"
    assert "International degree" in artifact.findings[0].title
    assert "pending credential verification" in artifact.findings[0].recommendation


def test_mock_registry_verified_credentials_are_info(tmp_path: Path) -> None:
    evidence_path = tmp_path / "credential_evidence.yaml"
    evidence_path.write_text(
        """
education_registry:
  - institution: State University
    degree: BS Information Systems
    status: verified
certification_registry:
  - name: Security+
    issuer: CompTIA
    status: verified
""",
        encoding="utf-8",
    )
    profile = _profile(
        education=[
            EducationRecord(
                institution="State University",
                degree="BS Information Systems",
                confidence=0.94,
            )
        ],
        certifications=[
            CertificationRecord(name="Security+", issuer="CompTIA", confidence=0.96)
        ],
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
        credential_evidence_path=evidence_path,
    )

    assert [finding.severity for finding in artifact.findings] == ["info", "info"]
    assert all(not finding.requires_human_review for finding in artifact.findings)
    assert all(finding.evidence for finding in artifact.findings)


def test_low_confidence_certification_routes_to_manual_review() -> None:
    profile = _profile(
        certifications=[
            CertificationRecord(
                name="Handwritten Safety License",
                issuer="Local Authority",
                confidence=0.31,
            )
        ]
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=profile,
    )

    finding = artifact.findings[0]
    assert finding.severity == "warning"
    assert finding.requires_human_review is True
    assert "manual credential review" in finding.recommendation


def test_low_confidence_bundle_evidence_creates_manual_review(tmp_path: Path) -> None:
    evidence_path = tmp_path / "credential_evidence.yaml"
    evidence_path.write_text(
        """
credential_evidence:
  type: handwritten_certificate_scan
  confidence: 0.31
  status: low_confidence_manual_review
""",
        encoding="utf-8",
    )

    artifact = build_credential_verification_findings(
        run_id="run_001",
        candidate_profile=_profile(),
        credential_evidence_path=evidence_path,
    )

    assert artifact.findings[0].title == "Mock credential evidence requires manual review"
    assert artifact.findings[0].evidence[0].source_type == "mock_credential_evidence"


def _profile(
    *,
    education: list[EducationRecord] | None = None,
    certifications: list[CertificationRecord] | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        education=education or [],
        certifications=certifications or [],
        extraction_confidence=0.97,
    )
