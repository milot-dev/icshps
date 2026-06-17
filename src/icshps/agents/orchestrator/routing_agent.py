from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Sequence

from icshps.agents.compliance.eeo_agent import build_eeo_compliance_findings
from icshps.schemas import (
    BundleContext,
    CandidateApplication,
    CandidateMatchResult,
    CandidateProfile,
    CandidateRoutingDecision,
    FinalDecisionArtifact,
    Finding,
    FindingCategory,
    FindingsArtifact,
    MatchResultsArtifact,
    RoutingCategory,
    Severity,
)
from icshps.services import RunScaffold, read_json_artifact

LOW_CONFIDENCE_THRESHOLD = 0.70
ADVANCE_SCORE_THRESHOLD = 80.0

_SEVERITY_PRIORITY: dict[Severity, int] = {
    Severity.BLOCKING: 0,
    Severity.ERROR: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}

_ROUTE_PRIORITY: tuple[RoutingCategory, ...] = (
    RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL,
    RoutingCategory.EEO_COMPLIANCE_REVIEW,
    RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW,
    RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
    RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
    RoutingCategory.MANUAL_REVIEW,
    RoutingCategory.SURGE_PROCESSING_MODE,
    RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
    RoutingCategory.FAST_TRACK_REVIEW,
)


def build_final_decision_from_run(
    scaffold: RunScaffold,
    *,
    candidate_profiles: Sequence[CandidateProfile] | None = None,
) -> FinalDecisionArtifact:
    """
    Build in-memory routing decisions from an existing run folder.

    Reads the generated run artifacts, validates them with existing schemas,
    merges findings, and returns a FinalDecisionArtifact.

    This does not write final_decision.json. Artifact writing belongs to the
    next task.
    """

    context_payload = read_json_artifact(scaffold=scaffold, artifact_key="context_packet")
    if context_payload is None:
        raise ValueError("Cannot build routing decisions without context_packet.json")

    context = BundleContext.model_validate(context_payload)
    candidate_profile = _read_optional_candidate_profile(scaffold)
    match_results = _read_optional_match_results(scaffold)
    intake_findings = _read_optional_findings(scaffold, "intake_findings")
    verification_findings = _read_optional_findings(scaffold, "verification_findings")
    anomaly_findings = _read_optional_findings(scaffold, "anomaly_findings")
    compliance_findings = build_eeo_compliance_findings(
        run_id=scaffold.run_id,
        job_description_path=context.required_inputs.job_description,
        job_title=context.job.title,
        eeo_policy_path=context.required_inputs.eeo_policy,
    )

    return build_final_decision_artifact(
        context=context,
        candidate_profile=candidate_profile,
        candidate_profiles=list(candidate_profiles or []),
        match_results=match_results,
        intake_findings=intake_findings,
        verification_findings=verification_findings,
        anomaly_findings=anomaly_findings,
        compliance_findings=compliance_findings,
    )


def build_final_decision_artifact(
    *,
    context: BundleContext,
    candidate_profile: CandidateProfile | None = None,
    candidate_profiles: list[CandidateProfile] | None = None,
    match_results: MatchResultsArtifact | None = None,
    intake_findings: FindingsArtifact | None = None,
    verification_findings: FindingsArtifact | None = None,
    anomaly_findings: FindingsArtifact | None = None,
    compliance_findings: FindingsArtifact | None = None,
) -> FinalDecisionArtifact:
    """
    Build the final decision object from validated in-memory inputs.
    This combines findings, removes duplicates, prioritizes issues, and creates
    one routing decision per candidate.
    """

    findings = collect_findings(
        candidate_profile=candidate_profile,
        candidate_profiles=candidate_profiles,
        match_results=match_results,
        intake_findings=intake_findings,
        verification_findings=verification_findings,
        anomaly_findings=anomaly_findings,
        compliance_findings=compliance_findings,
    )
    unified_findings = prioritize_findings(deduplicate_findings(findings))
    decisions = build_candidate_routing_decisions(
        context=context,
        candidate_profile=candidate_profile,
        candidate_profiles=candidate_profiles,
        match_results=match_results,
        findings=unified_findings,
    )

    return FinalDecisionArtifact(
        run_id=context.run_id,
        bundle_id=context.bundle.id,
        scenario_type=context.scenario.type,
        decisions=decisions,
        findings=unified_findings,
        summary=_build_summary(decisions=decisions, findings=unified_findings),
    )


def collect_findings(
    *,
    candidate_profile: CandidateProfile | None = None,
    candidate_profiles: list[CandidateProfile] | None = None,
    match_results: MatchResultsArtifact | None = None,
    intake_findings: FindingsArtifact | None = None,
    verification_findings: FindingsArtifact | None = None,
    anomaly_findings: FindingsArtifact | None = None,
    compliance_findings: FindingsArtifact | None = None,
) -> list[Finding]:
    """
    Collect findings and routing signals from all available pipeline outputs.

    This includes intake findings, match results, verification findings, anomaly
    findings, compliance findings, and candidate profile confidence signals.
    """

    findings: list[Finding] = []

    for artifact in (
        intake_findings,
        verification_findings,
        anomaly_findings,
        compliance_findings,
    ):
        if artifact is not None:
            findings.extend(artifact.findings)

    if match_results is not None:
        for result in _ordered_match_results(match_results.results):
            findings.extend(result.findings)
            findings.extend(_missing_mandatory_findings(result))

    profiles = _ordered_profiles(candidate_profiles or [])
    if not profiles and candidate_profile is not None:
        profiles = [candidate_profile]

    for profile in profiles:
        findings.extend(_candidate_profile_findings(profile))

    return findings


def deduplicate_findings(findings: Iterable[Finding]) -> list[Finding]:
    """
    Remove duplicate findings using stable deterministic keys.

    If duplicates conflict, the highest-severity finding is kept.
    """

    deduped: dict[str, Finding] = {}

    for finding in findings:
        key = _dedupe_key(finding)
        current = deduped.get(key)
        if current is None or _is_higher_priority(finding, current):
            deduped[key] = finding

    return list(deduped.values())


def prioritize_findings(findings: Iterable[Finding]) -> list[Finding]:
    """
    Sort findings by importance in a deterministic order.

    Blocking findings come first, followed by errors, warnings, and info.
    """

    return sorted(findings, key=_finding_sort_key)


def build_candidate_routing_decisions(
    *,
    context: BundleContext,
    candidate_profile: CandidateProfile | None = None,
    candidate_profiles: list[CandidateProfile] | None = None,
    match_results: MatchResultsArtifact | None = None,
    findings: Sequence[Finding],
) -> list[CandidateRoutingDecision]:
    """
    Build candidate-level routing recommendations.

    Applies the canonical routing priority and keeps every recommendation
    human-review-safe by requiring human approval.
    """

    matches_by_application = _match_results_by_application(match_results)
    candidates = _routing_candidates(
        context,
        match_results,
        candidate_profile,
        candidate_profiles or [],
    )
    decisions: list[CandidateRoutingDecision] = []

    for candidate in candidates:
        match = matches_by_application.get(candidate.application_id)
        candidate_findings = _findings_for_candidate(
            findings=findings,
            candidate_id=candidate.id,
            application_id=candidate.application_id,
        )
        routing_category = _select_routing_category(
            context=context,
            match=match,
            findings=candidate_findings,
        )
        route_findings = _route_findings(
            routing_category=routing_category,
            findings=candidate_findings,
        )

        decisions.append(
            CandidateRoutingDecision(
                candidate_id=candidate.id,
                application_id=candidate.application_id,
                routing_category=routing_category,
                reason=_routing_reason(
                    routing_category=routing_category,
                    match=match,
                    findings=route_findings,
                    context=context,
                ),
                score=match.score if match is not None else None,
                blocking_finding_ids=[finding.id for finding in route_findings],
                requires_human_approval=True,
            )
        )

    return sorted(
        decisions,
        key=lambda decision: (decision.candidate_id, decision.application_id),
    )


def _read_optional_findings(
    scaffold: RunScaffold,
    artifact_key: str,
) -> FindingsArtifact | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key=artifact_key)
    return FindingsArtifact.model_validate(payload) if payload is not None else None


def _read_optional_match_results(scaffold: RunScaffold) -> MatchResultsArtifact | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="match_scores")
    return MatchResultsArtifact.model_validate(payload) if payload is not None else None


def _read_optional_candidate_profile(scaffold: RunScaffold) -> CandidateProfile | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="candidate_profile")
    return CandidateProfile.model_validate(payload) if payload is not None else None


def _missing_mandatory_findings(result: CandidateMatchResult) -> list[Finding]:
    findings: list[Finding] = []

    for requirement in sorted(result.missing_mandatory_requirements):
        findings.append(
            Finding(
                id=_stable_id(
                    "match-missing-mandatory",
                    result.candidate_id,
                    result.application_id,
                    requirement,
                ),
                source_agent="orchestrator_routing_v1",
                category=FindingCategory.MATCHING,
                severity=Severity.BLOCKING,
                title="Missing mandatory requirement",
                description=f"Candidate is missing mandatory requirement: {requirement}.",
                reason=f"Missing mandatory requirement: {requirement}.",
                candidate_id=result.candidate_id,
                application_id=result.application_id,
                confidence=1.0,
                recommendation="Route as recommended rejection pending human approval.",
                requires_human_review=True,
            )
        )

    return findings


def _candidate_profile_findings(profile: CandidateProfile) -> list[Finding]:
    findings: list[Finding] = []

    if profile.extraction_confidence < LOW_CONFIDENCE_THRESHOLD:
        findings.append(
            Finding(
                id=_stable_id(
                    "profile-low-confidence",
                    profile.candidate_id,
                    profile.application_id,
                    str(profile.extraction_confidence),
                ),
                source_agent="orchestrator_routing_v1",
                category=FindingCategory.EXTRACTION,
                severity=Severity.WARNING,
                title="Low-confidence candidate profile extraction",
                description=(
                    "Candidate profile extraction confidence is below the "
                    f"routing threshold of {LOW_CONFIDENCE_THRESHOLD:.2f}."
                ),
                reason="Low-confidence extraction should be checked by a human reviewer.",
                candidate_id=profile.candidate_id,
                application_id=profile.application_id,
                confidence=profile.extraction_confidence,
                evidence=profile.evidence_index,
                recommendation="Route to manual review before using extracted fields.",
                requires_human_review=True,
            )
        )

    if profile.synthetic_fallback_used:
        findings.append(
            Finding(
                id=_stable_id(
                    "profile-synthetic-fallback",
                    profile.candidate_id,
                    profile.application_id,
                ),
                source_agent="orchestrator_routing_v1",
                category=FindingCategory.EXTRACTION,
                severity=Severity.WARNING,
                title="Synthetic candidate profile fallback used",
                description="Candidate profile used deterministic synthetic fallback data.",
                reason="Synthetic fallback output must be manually reviewed.",
                candidate_id=profile.candidate_id,
                application_id=profile.application_id,
                confidence=1.0,
                evidence=profile.evidence_index,
                recommendation="Route to manual review before final recommendation.",
                requires_human_review=True,
            )
        )

    for index, flag in enumerate(sorted(profile.manual_review_flags), start=1):
        findings.append(
            Finding(
                id=_stable_id(
                    "profile-manual-review",
                    profile.candidate_id,
                    profile.application_id,
                    str(index),
                    flag,
                ),
                source_agent="orchestrator_routing_v1",
                category=FindingCategory.EXTRACTION,
                severity=Severity.WARNING,
                title="Candidate profile manual review flag",
                description=flag,
                reason=flag,
                candidate_id=profile.candidate_id,
                application_id=profile.application_id,
                confidence=1.0,
                recommendation="Route to manual review.",
                requires_human_review=True,
            )
        )

    return findings


def _routing_candidates(
    context: BundleContext,
    match_results: MatchResultsArtifact | None,
    candidate_profile: CandidateProfile | None,
    candidate_profiles: list[CandidateProfile],
) -> list[CandidateApplication]:
    candidates_by_key = {
        (candidate.id, candidate.application_id): candidate for candidate in context.candidates
    }

    if match_results is not None:
        for result in match_results.results:
            key = (result.candidate_id, result.application_id)
            if key not in candidates_by_key:
                candidates_by_key[key] = CandidateApplication(
                    id=result.candidate_id,
                    application_id=result.application_id,
                    name=None,
                    target_job_id=result.job_id,
                    resume_file=context.bundle_path,
                )

    if candidate_profile is not None:
        key = (candidate_profile.candidate_id, candidate_profile.application_id)
        if key not in candidates_by_key:
            candidates_by_key[key] = CandidateApplication(
                id=candidate_profile.candidate_id,
                application_id=candidate_profile.application_id,
                name=candidate_profile.full_name.value,
                target_job_id=candidate_profile.role_id,
                resume_file=context.bundle_path,
            )

    for profile in candidate_profiles:
        key = (profile.candidate_id, profile.application_id)
        if key not in candidates_by_key:
            candidates_by_key[key] = CandidateApplication(
                id=profile.candidate_id,
                application_id=profile.application_id,
                name=profile.full_name.value,
                target_job_id=profile.role_id,
                resume_file=context.bundle_path,
            )

    return [candidates_by_key[key] for key in sorted(candidates_by_key)]


def _select_routing_category(
    *,
    context: BundleContext,
    match: CandidateMatchResult | None,
    findings: Sequence[Finding],
) -> RoutingCategory:
    for category in _ROUTE_PRIORITY:
        if category == RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL:
            if any(_is_blocking_missing_mandatory(finding) for finding in findings):
                return category
        elif category == RoutingCategory.EEO_COMPLIANCE_REVIEW:
            if any(_is_eeo_finding(finding) for finding in findings):
                return category
        elif category == RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW:
            if any(_is_duplicate_or_multi_role_finding(finding) for finding in findings):
                return category
        elif category == RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY:
            if any(_is_employment_inconsistency_finding(finding) for finding in findings):
                return category
        elif category == RoutingCategory.CREDENTIAL_VERIFICATION_PENDING:
            if any(_is_pending_credential_finding(finding) for finding in findings) and not any(
                _is_manual_review_finding(finding) for finding in findings
            ):
                return category
        elif category == RoutingCategory.MANUAL_REVIEW:
            if any(_is_manual_review_finding(finding) for finding in findings):
                return category
        elif category == RoutingCategory.SURGE_PROCESSING_MODE:
            if any(_is_surge_finding(finding) for finding in findings):
                return category
        elif category == RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW:
            if _is_high_match(match) and not _is_clean_standard_application(context):
                return category
        elif category == RoutingCategory.FAST_TRACK_REVIEW:
            return category

    return RoutingCategory.MANUAL_REVIEW


def _route_findings(
    *,
    routing_category: RoutingCategory,
    findings: Sequence[Finding],
) -> list[Finding]:
    predicates = {
        RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL: _is_blocking_missing_mandatory,
        RoutingCategory.EEO_COMPLIANCE_REVIEW: _is_eeo_finding,
        RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW: _is_duplicate_or_multi_role_finding,
        RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY: _is_employment_inconsistency_finding,
        RoutingCategory.CREDENTIAL_VERIFICATION_PENDING: _is_pending_credential_finding,
        RoutingCategory.MANUAL_REVIEW: _is_manual_review_finding,
        RoutingCategory.SURGE_PROCESSING_MODE: _is_surge_finding,
    }
    predicate = predicates.get(routing_category)
    if predicate is None:
        return []

    return [finding for finding in findings if predicate(finding)]


def _routing_reason(
    *,
    routing_category: RoutingCategory,
    match: CandidateMatchResult | None,
    findings: Sequence[Finding],
    context: BundleContext,
) -> str:
    if findings:
        titles = "; ".join(finding.title for finding in findings[:3])
        return f"{routing_category.value}: {titles}. Human approval is required."

    if routing_category == RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW:
        score = match.score if match is not None else None
        return (
            "Candidate has a high match score "
            f"({score:.2f}) and no higher-priority findings. Human approval is required."
            if score is not None
            else "Candidate has no higher-priority findings. Human approval is required."
        )

    if routing_category == RoutingCategory.FAST_TRACK_REVIEW:
        return (
            "Clean application scenario with no higher-priority findings. "
            "Fast-track is only a review recommendation and still requires human approval."
            if _is_clean_standard_application(context)
            else "No higher-priority findings were detected. Human approval is required."
        )

    return f"{routing_category.value}. Human approval is required."


def _findings_for_candidate(
    *,
    findings: Sequence[Finding],
    candidate_id: str,
    application_id: str,
) -> list[Finding]:
    return [
        finding
        for finding in findings
        if (
            finding.candidate_id in (None, candidate_id)
            and finding.application_id in (None, application_id)
        )
    ]


def _dedupe_key(finding: Finding) -> str:
    if finding.id:
        return f"id:{finding.id}"

    return "|".join(
        (
            finding.candidate_id or "",
            finding.application_id or "",
            finding.category.value,
            finding.severity.value,
            _normalize_text(finding.title),
            _normalize_text(finding.source_agent),
        )
    )


def _is_higher_priority(candidate: Finding, current: Finding) -> bool:
    return _finding_sort_key(candidate) < _finding_sort_key(current)


def _finding_sort_key(finding: Finding) -> tuple[int, str, str, str, str, str]:
    return (
        _SEVERITY_PRIORITY[finding.severity],
        finding.candidate_id or "",
        finding.application_id or "",
        finding.category.value,
        _normalize_text(finding.title),
        finding.id,
    )


def _ordered_match_results(
    results: Iterable[CandidateMatchResult],
) -> list[CandidateMatchResult]:
    return sorted(results, key=lambda result: (result.candidate_id, result.application_id))


def _ordered_profiles(profiles: Iterable[CandidateProfile]) -> list[CandidateProfile]:
    return sorted(profiles, key=lambda profile: (profile.candidate_id, profile.application_id))


def _match_results_by_application(
    match_results: MatchResultsArtifact | None,
) -> dict[str, CandidateMatchResult]:
    if match_results is None:
        return {}

    return {
        result.application_id: result for result in _ordered_match_results(match_results.results)
    }


def _is_blocking_missing_mandatory(finding: Finding) -> bool:
    text = _finding_text(finding)
    return (
        finding.severity == Severity.BLOCKING
        and "mandatory" in text
        and any(token in text for token in ("missing", "does not include", "requirement"))
    )


def _is_eeo_finding(finding: Finding) -> bool:
    return finding.category == FindingCategory.COMPLIANCE


def _is_duplicate_or_multi_role_finding(finding: Finding) -> bool:
    text = _finding_text(finding)
    return "duplicate" in text or "multi role" in text or "multi-role" in text


def _is_employment_inconsistency_finding(finding: Finding) -> bool:
    text = _finding_text(finding)
    return finding.category == FindingCategory.LINKEDIN_CONSISTENCY or (
        "employment" in text
        and any(token in text for token in ("contradiction", "contradict", "inconsistency"))
    )


def _is_pending_credential_finding(finding: Finding) -> bool:
    text = _finding_text(finding)
    if _is_blocking_missing_mandatory(finding):
        return False

    credential_signal = finding.category == FindingCategory.CREDENTIAL or "credential" in text
    pending_signal = any(
        token in text
        for token in (
            "pending",
            "not yet verified",
            "unverified",
            "international degree",
            "verification required",
        )
    )
    return credential_signal and pending_signal


def _is_manual_review_finding(finding: Finding) -> bool:
    text = _finding_text(finding)
    if not finding.requires_human_review:
        return False

    return any(
        token in text
        for token in (
            "low confidence",
            "low-confidence",
            "manual review",
            "handwritten",
            "synthetic fallback",
            "extraction",
        )
    )


def _is_surge_finding(finding: Finding) -> bool:
    text = _finding_text(finding)
    return "surge" in text or "bulk application" in text or "viral job" in text


def _is_high_match(match: CandidateMatchResult | None) -> bool:
    return (
        match is not None
        and match.score >= ADVANCE_SCORE_THRESHOLD
        and not match.missing_mandatory_requirements
    )


def _is_clean_standard_application(context: BundleContext) -> bool:
    scenario_type = _normalize_text(context.scenario.type)
    tags = {_normalize_text(tag) for tag in context.scenario.tags}
    return scenario_type == "clean standard application" or "clean" in tags


def _finding_text(finding: Finding) -> str:
    return _normalize_text(
        " ".join(
            part
            for part in (
                finding.source_agent,
                finding.title,
                finding.description,
                finding.reason or "",
                finding.recommendation or "",
                finding.category.value,
            )
            if part
        )
    )


def _normalize_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _stable_id(*parts: str) -> str:
    raw = "|".join(_normalize_text(part) for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{parts[0]}-{digest}"


def _build_summary(
    *,
    decisions: Sequence[CandidateRoutingDecision],
    findings: Sequence[Finding],
) -> str:
    return (
        f"Prepared {len(decisions)} candidate routing decision(s) from "
        f"{len(findings)} unified deduplicated finding(s). "
        "All recommendations require human approval."
    )
