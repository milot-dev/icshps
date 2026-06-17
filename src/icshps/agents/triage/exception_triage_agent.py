from __future__ import annotations

import hashlib

from icshps.schemas import (
    EvidenceRef,
    FinalDecisionArtifact,
    Finding,
    FindingCategory,
    FindingsArtifact,
    RoutingCategory,
    Severity,
)

AGENT_NAME = "exception_triage_agent_v1"


def build_exception_triage_findings(
    *,
    final_decision: FinalDecisionArtifact,
) -> FindingsArtifact:
    """Create deterministic triage findings from final routing recommendations."""

    findings: list[Finding] = []
    source_findings = {finding.id: finding for finding in final_decision.findings}

    for decision in sorted(
        final_decision.decisions,
        key=lambda item: (item.candidate_id, item.application_id),
    ):
        severity = _severity_for_route(decision.routing_category)
        title = _title_for_route(decision.routing_category)
        source_refs = [
            source_findings[finding_id]
            for finding_id in sorted(decision.blocking_finding_ids)
            if finding_id in source_findings
        ]
        findings.append(
            Finding(
                id=_stable_id(
                    "triage",
                    decision.candidate_id,
                    decision.application_id,
                    decision.routing_category.value,
                ),
                source_agent=AGENT_NAME,
                category=FindingCategory.TRIAGE,
                severity=severity,
                title=title,
                description=(
                    f"Candidate routed to '{decision.routing_category.value}'. "
                    "Hiring manager follow-up is required before any action."
                ),
                reason=decision.reason,
                candidate_id=decision.candidate_id,
                application_id=decision.application_id,
                confidence=1.0,
                evidence=_triage_evidence(source_refs),
                recommendation=_recommendation_for_route(decision.routing_category),
                requires_human_review=True,
            )
        )

    return FindingsArtifact(run_id=final_decision.run_id, findings=findings)


def _severity_for_route(category: RoutingCategory) -> Severity:
    if category == RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL:
        return Severity.BLOCKING
    if category in {
        RoutingCategory.EEO_COMPLIANCE_REVIEW,
        RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW,
        RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
        RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
        RoutingCategory.MANUAL_REVIEW,
    }:
        return Severity.WARNING
    return Severity.INFO


def _title_for_route(category: RoutingCategory) -> str:
    if category == RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW:
        return "Interview routing follow-up"
    if category == RoutingCategory.FAST_TRACK_REVIEW:
        return "Fast-track manager review"
    if category == RoutingCategory.SURGE_PROCESSING_MODE:
        return "Surge processing triage"
    return "Exception triage follow-up"


def _recommendation_for_route(category: RoutingCategory) -> str:
    if category in {
        RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
        RoutingCategory.FAST_TRACK_REVIEW,
    }:
        return "Confirm interview readiness and human approval before scheduling."
    if category == RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL:
        return "Review blocking reasons and approve or overturn the rejection recommendation."
    return "Review exception evidence and assign the appropriate human follow-up owner."


def _triage_evidence(source_findings: list[Finding]) -> list[EvidenceRef]:
    evidence: list[EvidenceRef] = []
    for finding in source_findings:
        evidence.extend(finding.evidence)
    return evidence


def _stable_id(*parts: str) -> str:
    raw = "|".join(part.lower().strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]
    return f"{parts[0]}-{digest}"
