from __future__ import annotations

from pathlib import Path

from icshps.schemas.common import EvidenceRef, FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact
from icshps.services.compliance_flags_writer import (
    build_compliance_flags_markdown,
    write_compliance_flags_md,
)


def test_build_compliance_flags_markdown_with_no_findings_returns_stable_message() -> None:
    artifact = FindingsArtifact(run_id="run123", findings=[])

    content = build_compliance_flags_markdown(artifact)

    assert content.startswith("# Compliance Flags")
    assert "No compliance flags were detected." in content
    assert content.count("###") == 0


def test_build_compliance_flags_markdown_renders_eeo_and_certification_findings() -> None:
    eeo_finding = Finding(
        id="eeo-age-digital-native-001",
        source_agent="eeo_compliance_agent_v1",
        category=FindingCategory.COMPLIANCE,
        severity=Severity.WARNING,
        title="Age-specific job description language",
        description="Digital native wording was detected.",
        reason="This phrase may imply a preference for younger applicants.",
        recommendation="Review and rewrite the job description before publishing.",
        confidence=1.0,
        evidence=[
            EvidenceRef(
                source_path=Path("job_description.md"),
                source_type="job_description",
                section="line:3",
                text_snippet="digital native",
                confidence=1.0,
            )
        ],
    )

    cert_finding = Finding(
        id="certification-required-001",
        source_agent="mandatory_certification_check_v1",
        category=FindingCategory.MATCHING,
        severity=Severity.BLOCKING,
        title="Mandatory certification missing",
        description="Candidate profile does not include required certification 'AWS Certified Developer'.",
        reason="Candidate profile does not include required certification 'AWS Certified Developer'.",
        recommendation="Route as recommended rejection pending human approval.",
        confidence=1.0,
        candidate_id="candidate_001",
        application_id="app_001",
        evidence=[
            EvidenceRef(
                source_path=Path("skills_matrix.yaml"),
                source_type="skills_matrix",
                section="mandatory_certifications",
                text_snippet="AWS Certified Developer",
                confidence=1.0,
            )
        ],
    )

    artifact = FindingsArtifact(run_id="run123", findings=[eeo_finding, cert_finding])

    content = build_compliance_flags_markdown(artifact)

    assert "## EEO compliance findings" in content
    assert "## Mandatory certification findings" in content
    assert "### Age-specific job description language" in content
    assert "### Mandatory certification missing" in content
    assert "- severity: `warning`" in content
    assert "- severity: `blocking`" in content
    assert "- confidence: 1.00" in content
    assert "- requires_human_review: Yes" in content
    assert "- evidence:" in content
    assert "job_description:line:3" in content
    assert "skills_matrix:mandatory_certifications" in content


def test_compliance_flags_markdown_includes_credential_anomaly_and_routing_summaries() -> None:
    credential_finding = Finding(
        id="credential-education-pending-001",
        source_agent="credential_verification_agent_v1",
        category=FindingCategory.CREDENTIAL,
        severity=Severity.WARNING,
        title="International degree pending verification",
        description="Education credential needs mock registry verification.",
        reason="International education requires pending verification.",
        recommendation="Route to pending credential verification.",
        evidence=[
            EvidenceRef(
                source_path=Path("credential_evidence.yaml"),
                source_type="mock_credential_evidence",
                section="education",
                text_snippet="International Technical University",
            )
        ],
    )
    anomaly_finding = Finding(
        id="anomaly-multi-role-001",
        source_agent="anomaly_detection_agent_v1",
        category=FindingCategory.ANOMALY,
        severity=Severity.WARNING,
        title="Candidate applied to multiple roles",
        description="Candidate appears across three roles.",
        reason="Multi-role applications require reviewer grouping.",
        recommendation="Route to duplicate / multi-role review.",
        evidence=[
            EvidenceRef(
                source_path=Path("application_history.yaml"),
                source_type="mock_application_history",
                section="applications",
                text_snippet="job_backend, job_ml, job_data",
            )
        ],
    )
    routing_finding = Finding(
        id="triage-routing-001",
        source_agent="exception_triage_agent_v1",
        category=FindingCategory.TRIAGE,
        severity=Severity.INFO,
        title="Routing recommendation",
        description="Pending credential verification. Human approval required.",
        reason="Credential finding requires reviewer routing.",
        recommendation="Pending credential verification; human approval required.",
    )

    content = build_compliance_flags_markdown(
        FindingsArtifact(
            run_id="run123",
            findings=[credential_finding, anomaly_finding, routing_finding],
        )
    )

    assert "## Credential verification summary" in content
    assert "## Anomaly summary" in content
    assert "## Routing recommendation summary" in content
    assert "International degree pending verification" in content
    assert "Candidate applied to multiple roles" in content
    assert "human approval required" in content.lower()


def test_write_compliance_flags_md_writes_file(tmp_path: Path) -> None:
    artifact = FindingsArtifact(run_id="run123", findings=[])
    output_path = tmp_path / "compliance_flags.md"

    write_compliance_flags_md(output_path, artifact)

    assert output_path.exists()
    content = output_path.read_text(encoding="utf-8")
    assert "No compliance flags were detected." in content


def test_compliance_flags_markdown_is_deterministic(tmp_path: Path) -> None:
    eeo_finding = Finding(
        id="eeo-age-digital-native-001",
        source_agent="eeo_compliance_agent_v1",
        category=FindingCategory.COMPLIANCE,
        severity=Severity.WARNING,
        title="Age-specific job description language",
        description="Digital native wording was detected.",
        reason="This phrase may imply a preference for younger applicants.",
        recommendation="Review and rewrite the job description before publishing.",
        confidence=1.0,
        evidence=[
            EvidenceRef(
                source_path=Path("job_description.md"),
                source_type="job_description",
                section="line:3",
                text_snippet="digital native",
                confidence=1.0,
            ),
            EvidenceRef(
                source_path=Path("job_description.md"),
                source_type="job_description",
                section="line:2",
                text_snippet="recent graduate",
                confidence=1.0,
            ),
        ],
    )

    artifact = FindingsArtifact(run_id="run123", findings=[eeo_finding])
    first = build_compliance_flags_markdown(artifact)
    second = build_compliance_flags_markdown(artifact)

    assert first == second
    assert first.count("- evidence:") == 1
    assert first.index("line:2") < first.index("line:3")
