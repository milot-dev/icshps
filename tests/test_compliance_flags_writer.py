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
