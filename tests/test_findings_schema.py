from pathlib import Path

from icshps.schemas.common import EvidenceRef, FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact


def test_unified_finding_schema_supports_member_3_required_fields() -> None:
    finding = Finding(
        id="eeo-age-digital-native-001",
        source_agent="eeo_compliance_agent_v1",
        category=FindingCategory.COMPLIANCE,
        severity=Severity.WARNING,
        title="Age-specific job description language",
        description="Digital native wording was detected.",
        reason="This phrase may imply a preference for younger applicants.",
        evidence=[
            EvidenceRef(
                source_path=Path("job_description.md"),
                source_type="job_description",
                section="line:3",
                text_snippet="digital native",
            )
        ],
    )

    assert finding.id == "eeo-age-digital-native-001"
    assert finding.created_at == "1970-01-01T00:00:00Z"
    assert finding.reason is not None
    assert finding.evidence[0].text_snippet == "digital native"


def test_findings_example_json_is_valid() -> None:
    example_path = Path("data/sample_outputs/findings.example.json")

    artifact = FindingsArtifact.model_validate_json(example_path.read_text())

    assert artifact.findings[0].category == FindingCategory.COMPLIANCE
