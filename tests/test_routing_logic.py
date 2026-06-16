from __future__ import annotations

from pathlib import Path

from icshps.agents.orchestrator.routing_agent import (
    build_final_decision_artifact,
    collect_findings,
    deduplicate_findings,
)
from icshps.schemas import (
    BundleContext,
    BundleInfo,
    CandidateApplication,
    CandidateMatchResult,
    CandidateProfile,
    ExtractedField,
    Finding,
    FindingCategory,
    FindingsArtifact,
    JobInfo,
    MatchResultsArtifact,
    OptionalInputPaths,
    RequiredInputPaths,
    RoutingCategory,
    ScenarioInfo,
    Severity,
)


def test_duplicate_findings_are_removed_and_highest_priority_is_kept() -> None:
    duplicate_info = finding(
        id="same-finding",
        severity=Severity.INFO,
        title="Duplicate issue",
    )
    duplicate_blocking = finding(
        id="same-finding",
        severity=Severity.BLOCKING,
        title="Duplicate issue",
    )

    result = deduplicate_findings([duplicate_info, duplicate_blocking])

    assert len(result) == 1
    assert result[0].severity == Severity.BLOCKING


def test_blocking_missing_mandatory_overrides_high_match_score() -> None:
    artifact = build_final_decision_artifact(
        context=context(scenario_type="strong_match"),
        match_results=match_results(
            score=96.0,
            missing_mandatory_requirements=["certification: Security+"],
        ),
    )

    decision = artifact.decisions[0]

    assert decision.routing_category == RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL
    assert decision.requires_human_approval is True
    assert decision.blocking_finding_ids


def test_eeo_findings_route_to_eeo_review() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        match_results=match_results(score=95.0),
        compliance_findings=FindingsArtifact(
            run_id="run_001",
            findings=[
                finding(
                    id="eeo-age-001",
                    category=FindingCategory.COMPLIANCE,
                    severity=Severity.WARNING,
                    title="Age-specific job description language",
                )
            ],
        ),
    )

    assert artifact.decisions[0].routing_category == RoutingCategory.EEO_COMPLIANCE_REVIEW


def test_credential_pending_findings_route_correctly() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        match_results=match_results(score=91.0),
        verification_findings=FindingsArtifact(
            run_id="run_001",
            findings=[
                finding(
                    id="credential-pending-001",
                    category=FindingCategory.CREDENTIAL,
                    severity=Severity.WARNING,
                    title="International degree not yet verified",
                    description="Credential verification is pending.",
                )
            ],
        ),
    )

    assert artifact.decisions[0].routing_category == (
        RoutingCategory.CREDENTIAL_VERIFICATION_PENDING
    )


def test_employment_inconsistency_routes_correctly() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        match_results=match_results(score=92.0),
        anomaly_findings=FindingsArtifact(
            run_id="run_001",
            findings=[
                finding(
                    id="linkedin-dates-001",
                    category=FindingCategory.LINKEDIN_CONSISTENCY,
                    severity=Severity.WARNING,
                    title="Employment history inconsistency",
                    description="Resume employment dates contradict LinkedIn dates.",
                )
            ],
        ),
    )

    assert artifact.decisions[0].routing_category == (
        RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY
    )


def test_duplicate_multi_role_findings_route_correctly() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        match_results=match_results(score=90.0),
        anomaly_findings=FindingsArtifact(
            run_id="run_001",
            findings=[
                finding(
                    id="duplicate-multi-role-001",
                    category=FindingCategory.ANOMALY,
                    severity=Severity.WARNING,
                    title="Duplicate / multi-role application detected",
                    description="Candidate applied to multiple roles.",
                )
            ],
        ),
    )

    assert artifact.decisions[0].routing_category == RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW


def test_clean_high_score_candidate_routes_to_fast_track_review() -> None:
    artifact = build_final_decision_artifact(
        context=context(scenario_type="clean_standard_application", tags=["clean"]),
        match_results=match_results(score=100.0),
    )

    assert artifact.decisions[0].routing_category == RoutingCategory.FAST_TRACK_REVIEW


def test_strong_high_score_candidate_routes_to_interview_review() -> None:
    artifact = build_final_decision_artifact(
        context=context(scenario_type="strong_match"),
        match_results=match_results(score=94.0),
    )

    assert artifact.decisions[0].routing_category == (
        RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW
    )


def test_low_confidence_profile_routes_to_manual_review() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        candidate_profile=profile(extraction_confidence=0.42),
        match_results=match_results(score=92.0),
    )

    assert artifact.decisions[0].routing_category == RoutingCategory.MANUAL_REVIEW


def test_all_routing_decisions_require_human_approval() -> None:
    artifact = build_final_decision_artifact(
        context=context(scenario_type="strong_match"),
        match_results=match_results(score=95.0),
    )

    assert all(decision.requires_human_approval for decision in artifact.decisions)


def test_routing_output_is_deterministic() -> None:
    kwargs = {
        "context": context(scenario_type="strong_match"),
        "match_results": match_results(score=95.0),
    }

    first = build_final_decision_artifact(**kwargs)
    second = build_final_decision_artifact(**kwargs)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_canonical_routing_labels_are_used() -> None:
    artifact = build_final_decision_artifact(
        context=context(),
        match_results=match_results(score=91.0),
        verification_findings=FindingsArtifact(
            run_id="run_001",
            findings=[
                finding(
                    id="credential-pending-001",
                    category=FindingCategory.CREDENTIAL,
                    severity=Severity.WARNING,
                    title="International degree not yet verified",
                )
            ],
        ),
    )

    actual_values = {decision.routing_category.value for decision in artifact.decisions}
    canonical_values = {category.value for category in RoutingCategory}

    assert actual_values <= canonical_values
    assert "Pending credential verification" not in actual_values
    assert "Manual credential review" not in actual_values
    assert "Employment history inconsistency — manual review" not in actual_values


def test_collect_findings_adds_missing_mandatory_match_signal() -> None:
    collected = collect_findings(
        match_results=match_results(
            score=88.0,
            missing_mandatory_requirements=["certification: Security+"],
        )
    )

    assert any(item.severity == Severity.BLOCKING for item in collected)
    assert any(item.title == "Missing mandatory requirement" for item in collected)


def context(
    *,
    scenario_type: str = "credential_pending",
    tags: list[str] | None = None,
) -> BundleContext:
    return BundleContext(
        run_id="run_001",
        bundle_path=Path("bundle"),
        bundle=BundleInfo(id="bundle_001", name="Bundle 001"),
        scenario=ScenarioInfo(
            id="scenario_001",
            type=scenario_type,
            expected_routing=None,
            tags=tags or [],
        ),
        job=JobInfo(id="job_001", title="AI Backend Engineer"),
        candidates=[
            CandidateApplication(
                id="candidate_001",
                application_id="app_001",
                name="Sample Candidate",
                target_job_id="job_001",
                resume_file=Path("resume.pdf"),
            )
        ],
        required_inputs=RequiredInputPaths(
            job_description=Path("job_description.md"),
            skills_matrix=Path("skills_matrix.yaml"),
            eeo_policy=Path("eeo_policy.yaml"),
            credential_rules=Path("credential_rules.yaml"),
            hris_master=Path("hris_master.yaml"),
        ),
        optional_inputs=OptionalInputPaths(),
        is_ready=True,
    )


def match_results(
    *,
    score: float = 85.0,
    missing_mandatory_requirements: list[str] | None = None,
) -> MatchResultsArtifact:
    return MatchResultsArtifact(
        run_id="run_001",
        results=[
            CandidateMatchResult(
                candidate_id="candidate_001",
                application_id="app_001",
                job_id="job_001",
                score=score,
                missing_mandatory_requirements=missing_mandatory_requirements or [],
            )
        ],
    )


def profile(*, extraction_confidence: float = 0.95) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        extraction_confidence=extraction_confidence,
    )


def finding(
    *,
    id: str,
    category: FindingCategory = FindingCategory.ANOMALY,
    severity: Severity = Severity.WARNING,
    title: str,
    description: str | None = None,
    candidate_id: str | None = "candidate_001",
    application_id: str | None = "app_001",
) -> Finding:
    return Finding(
        id=id,
        source_agent="test_agent",
        category=category,
        severity=severity,
        title=title,
        description=description or title,
        reason=description or title,
        candidate_id=candidate_id,
        application_id=application_id,
        requires_human_review=True,
    )
