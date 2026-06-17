from __future__ import annotations

from icshps.schemas.common import FindingCategory, RoutingCategory, Severity
from icshps.schemas.decision import CandidateRoutingDecision, FinalDecisionArtifact
from icshps.schemas.findings import Finding
from icshps.schemas.matching import CandidateMatchResult

AGENT_NAME = "exception_triage_agent_v1"


def build_exception_triage_decisions(
    *,
    run_id: str,
    bundle_id: str,
    scenario_type: str,
    findings: list[Finding],
    match_results: list[CandidateMatchResult] | None = None,
) -> FinalDecisionArtifact:
    """Group findings into human-review routing recommendations without final hiring decisions."""

    deduped_findings = _dedupe_findings(findings)
    match_by_candidate = {
        result.candidate_id: result for result in (match_results or [])
    }
    candidate_ids = sorted(
        {
            finding.candidate_id
            for finding in deduped_findings
            if finding.candidate_id is not None
        }
        | set(match_by_candidate)
    )

    decisions = [
        _decision_for_candidate(
            candidate_id=candidate_id,
            findings=[
                finding
                for finding in deduped_findings
                if finding.candidate_id in {None, candidate_id}
            ],
            match_result=match_by_candidate.get(candidate_id),
        )
        for candidate_id in candidate_ids
    ]

    return FinalDecisionArtifact(
        run_id=run_id,
        bundle_id=bundle_id,
        scenario_type=scenario_type,
        decisions=decisions,
        findings=deduped_findings,
        summary="Routing recommendations require human approval and are not final hiring decisions.",
    )


def _decision_for_candidate(
    *,
    candidate_id: str,
    findings: list[Finding],
    match_result: CandidateMatchResult | None,
) -> CandidateRoutingDecision:
    application_id = _application_id(findings, match_result)
    blocking = [finding for finding in findings if finding.severity == Severity.BLOCKING]
    routing_category = _routing_category(findings=findings, has_blocking=bool(blocking), match_result=match_result)

    return CandidateRoutingDecision(
        candidate_id=candidate_id,
        application_id=application_id,
        routing_category=routing_category,
        reason=_reason_for(routing_category),
        score=match_result.score if match_result else None,
        blocking_finding_ids=[finding.id for finding in blocking],
        requires_human_approval=True,
    )


def _routing_category(
    *,
    findings: list[Finding],
    has_blocking: bool,
    match_result: CandidateMatchResult | None,
) -> RoutingCategory:
    if has_blocking:
        return RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL
    if any(finding.category == FindingCategory.COMPLIANCE for finding in findings):
        return RoutingCategory.EEO_COMPLIANCE_REVIEW
    if any(finding.category == FindingCategory.LINKEDIN_CONSISTENCY for finding in findings):
        return RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY
    if any("manual credential review" in (finding.recommendation or "").lower() for finding in findings):
        return RoutingCategory.MANUAL_REVIEW
    if any(finding.category == FindingCategory.CREDENTIAL for finding in findings):
        return RoutingCategory.CREDENTIAL_VERIFICATION_PENDING
    if any("duplicate / multi-role" in (finding.recommendation or "").lower() for finding in findings):
        return RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW
    if any("surge processing" in (finding.title + " " + (finding.recommendation or "")).lower() for finding in findings):
        return RoutingCategory.SURGE_PROCESSING_MODE
    if match_result and match_result.recommendation_signal == "strong_match":
        return RoutingCategory.FAST_TRACK_REVIEW
    return RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW


def _reason_for(category: RoutingCategory) -> str:
    reasons = {
        RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL: "Blocking issue found; recommended rejection requires human approval.",
        RoutingCategory.EEO_COMPLIANCE_REVIEW: "EEO or protected-language compliance finding requires review.",
        RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY: "Employment history inconsistency requires manual review.",
        RoutingCategory.MANUAL_REVIEW: "Manual credential review is required.",
        RoutingCategory.CREDENTIAL_VERIFICATION_PENDING: "Credential verification is pending or incomplete.",
        RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW: "Duplicate or multi-role application pattern requires review.",
        RoutingCategory.SURGE_PROCESSING_MODE: "Surge metadata changes reviewer prioritization.",
        RoutingCategory.FAST_TRACK_REVIEW: "Strong match with no higher-priority exception found.",
        RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW: "No blocking exception found; advance for human interview review.",
    }
    return reasons[category]


def _application_id(findings: list[Finding], match_result: CandidateMatchResult | None) -> str:
    if match_result is not None:
        return match_result.application_id
    for finding in findings:
        if finding.application_id:
            return finding.application_id
    return "unknown_application"


def _dedupe_findings(findings: list[Finding]) -> list[Finding]:
    deduped: list[Finding] = []
    seen: set[tuple[str, str | None, str | None]] = set()
    for finding in findings:
        key = (finding.id, finding.candidate_id, finding.application_id)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped
