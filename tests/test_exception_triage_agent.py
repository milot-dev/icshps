from icshps.agents.triage import (
    build_exception_triage_decisions,
    render_compliance_flags_markdown,
)
from icshps.schemas.common import FindingCategory, Severity
from icshps.schemas.findings import Finding
from icshps.schemas.matching import CandidateMatchResult


def test_exception_triage_routes_blocking_findings_to_human_approval_rejection() -> None:
    finding = Finding(
        id="certification-required-001",
        source_agent="mandatory_certification_check_v1",
        category=FindingCategory.MATCHING,
        severity=Severity.BLOCKING,
        title="Mandatory certification missing",
        description="Missing certification.",
        reason="Candidate lacks a mandatory certification.",
        candidate_id="candidate_001",
        application_id="app_001",
    )

    artifact = build_exception_triage_decisions(
        run_id="run_001",
        bundle_id="bundle_001",
        scenario_type="missing_certification",
        findings=[finding],
    )

    decision = artifact.decisions[0]
    assert decision.routing_category.value.startswith("Recommended rejection")
    assert decision.blocking_finding_ids == ["certification-required-001"]
    assert decision.requires_human_approval is True


def test_exception_triage_fast_tracks_strong_match_without_exceptions() -> None:
    match_result = CandidateMatchResult(
        candidate_id="candidate_001",
        application_id="app_001",
        job_id="job_001",
        score=95.0,
        recommendation_signal="strong_match",
    )

    artifact = build_exception_triage_decisions(
        run_id="run_001",
        bundle_id="bundle_001",
        scenario_type="clean_standard_application",
        findings=[],
        match_results=[match_result],
    )

    assert artifact.decisions[0].routing_category == "Fast-track review"


def test_compliance_flags_markdown_includes_findings_and_disclaimer() -> None:
    finding = Finding(
        id="eeo-age-digital-native-001",
        source_agent="eeo_compliance_agent_v1",
        category=FindingCategory.COMPLIANCE,
        severity=Severity.WARNING,
        title="Age-specific job description language",
        description="Risky language.",
        reason="Digital native can imply age preference.",
        recommendation="Review JD wording.",
    )

    markdown = render_compliance_flags_markdown(
        run_id="run_001",
        findings=[finding],
    )

    assert "# Compliance Flags" in markdown
    assert "All routing recommendations require human approval" in markdown
    assert "Age-specific job description language" in markdown
