from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path
from typing import Any

from icshps.schemas import (
    BundleContext,
    CandidateProfile,
    CandidateRoutingDecision,
    FinalDecisionArtifact,
    MatchResultsArtifact,
    RoutingCategory,
    Severity,
)
from icshps.services.artifact_writer import (
    artifact_path,
    mark_artifacts_created,
    read_json_artifact,
    write_json_artifact,
)
from icshps.services.candidate_artifacts import read_candidate_profiles
from icshps.services.run_scaffolding import V2_METRIC_DEFAULTS, RunScaffold

FINAL_ARTIFACT_KEYS: tuple[str, ...] = (
    "final_decision",
    "shortlist",
    "hiring_packet",
    "metrics",
    "audit_log",
)

SHORTLIST_COLUMNS: tuple[str, ...] = (
    "rank",
    "candidate_id",
    "application_id",
    "routing_category",
    "score",
    "requires_human_approval",
    "reason",
)

_ROUTE_RANK: dict[RoutingCategory, int] = {
    RoutingCategory.FAST_TRACK_REVIEW: 0,
    RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW: 1,
    RoutingCategory.SURGE_PROCESSING_MODE: 2,
    RoutingCategory.CREDENTIAL_VERIFICATION_PENDING: 3,
    RoutingCategory.MANUAL_REVIEW: 4,
    RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY: 5,
    RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW: 6,
    RoutingCategory.EEO_COMPLIANCE_REVIEW: 7,
    RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL: 8,
}

_SEVERITY_RANK: dict[Severity, int] = {
    Severity.BLOCKING: 0,
    Severity.ERROR: 1,
    Severity.WARNING: 2,
    Severity.INFO: 3,
}


def write_final_run_artifacts(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
    candidate_profiles: list[CandidateProfile] | None = None,
) -> tuple[Path, ...]:
    """
    Write all Task 5 final artifacts for one completed backend run.

    This consumes Task 4 routing output and writes demo-ready JSON, CSV,
    and Markdown artifacts without changing routing labels or upstream contracts.
    """

    context = _read_optional_context(scaffold)
    candidate_profile = _read_optional_candidate_profile(scaffold)
    resolved_candidate_profiles = (
        candidate_profiles
        if candidate_profiles is not None
        else read_candidate_profiles(scaffold)
    )
    match_results = _read_optional_match_results(scaffold)

    paths = (
        write_final_decision_artifact(
            scaffold=scaffold,
            final_decision=final_decision,
        ),
        write_shortlist_csv(
            scaffold=scaffold,
            final_decision=final_decision,
        ),
        write_hiring_packet(
            scaffold=scaffold,
            final_decision=final_decision,
            context=context,
            candidate_profile=candidate_profile,
            candidate_profiles=resolved_candidate_profiles,
            match_results=match_results,
        ),
        write_metrics(
            scaffold=scaffold,
            final_decision=final_decision,
            context=context,
        ),
        write_audit_log(
            scaffold=scaffold,
            final_decision=final_decision,
            context=context,
        ),
    )

    mark_final_artifacts_created(scaffold)
    return paths


def write_final_decision_artifact(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
) -> Path:
    """Write the schema-validated final routing artifact."""

    return write_json_artifact(
        scaffold=scaffold,
        artifact_key="final_decision",
        payload=final_decision,
        mark_created=False,
    )


def write_shortlist_csv(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
) -> Path:
    """Write deterministic shortlist rows from final routing decisions."""

    path = artifact_path(scaffold, "shortlist")
    path.parent.mkdir(parents=True, exist_ok=True)

    ordered_decisions = _ordered_shortlist_decisions(final_decision.decisions)

    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=SHORTLIST_COLUMNS)
        writer.writeheader()

        for rank, decision in enumerate(ordered_decisions, start=1):
            writer.writerow(
                {
                    "rank": rank,
                    "candidate_id": decision.candidate_id,
                    "application_id": decision.application_id,
                    "routing_category": decision.routing_category.value,
                    "score": _format_score(decision.score),
                    "requires_human_approval": str(
                        decision.requires_human_approval
                    ).lower(),
                    "reason": decision.reason,
                }
            )

    return path


def write_hiring_packet(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
    context: BundleContext | None = None,
    candidate_profile: CandidateProfile | None = None,
    candidate_profiles: list[CandidateProfile] | None = None,
    match_results: MatchResultsArtifact | None = None,
) -> Path:
    """Write a simplified local-only mock hiring packet for human review."""

    payload: dict[str, Any] = {
        "run_id": final_decision.run_id,
        "bundle_id": final_decision.bundle_id,
        "scenario_type": final_decision.scenario_type,
        "job": _job_summary(context),
        "candidate_summaries": [
            _candidate_packet_summary(
                decision=decision,
                context=context,
                candidate_profile=candidate_profile,
                candidate_profiles=candidate_profiles or [],
                match_results=match_results,
            )
            for decision in _ordered_decisions(final_decision.decisions)
        ],
        "artifact_references": {
            "candidate_profile": "artifacts/candidate_profile.json",
            "candidate_profiles": "artifacts/candidate_profiles.json",
            "match_scores": "artifacts/match_scores.json",
            "unified_findings": "artifacts/final_decision.json#findings",
            "shortlist": "artifacts/shortlist.csv",
            "audit_log": "artifacts/audit_log.md",
        },
        "mock_hris_payload_note": (
            "Local demo-only mock payload. ICSHPS does not post to a real HRIS, "
            "ATS, email system, calendar, background-check provider, or LinkedIn. "
            "All routing recommendations require human approval."
        ),
        "requires_human_approval": True,
        "final_hiring_decision_made_by_system": False,
    }

    return write_json_artifact(
        scaffold=scaffold,
        artifact_key="hiring_packet",
        payload=payload,
        mark_created=False,
    )


def write_metrics(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
    context: BundleContext | None = None,
) -> Path:
    """Write deterministic summary metrics for the completed local run."""

    existing_metrics = read_json_artifact(scaffold=scaffold, artifact_key="metrics") or {}
    routing_counts = Counter(
        decision.routing_category.value for decision in final_decision.decisions
    )
    total_candidates = len(context.candidates) if context else len(final_decision.decisions)
    blocking_finding_count = sum(
        1 for finding in final_decision.findings if finding.severity == Severity.BLOCKING
    )
    manual_review_decisions = [
        decision
        for decision in final_decision.decisions
        if _is_manual_review_routing(decision.routing_category)
    ]
    compliance_flag_count = _candidate_count_with_category(
        final_decision=final_decision,
        categories={"compliance"},
    )
    credential_issue_count = _candidate_count_with_category(
        final_decision=final_decision,
        categories={"credential", "matching"},
        title_tokens=("certification", "credential"),
    )
    anomaly_count = _candidate_count_with_category(
        final_decision=final_decision,
        categories={"anomaly", "linkedin_consistency"},
    )
    manual_review_count = len(manual_review_decisions)

    payload: dict[str, Any] = {
        **existing_metrics,
        "run_id": final_decision.run_id,
        "bundle_id": final_decision.bundle_id,
        "scenario_type": final_decision.scenario_type,
        "candidate_count": total_candidates,
        **_v2_metric_values(scaffold),
        "total_candidates": total_candidates,
        "decision_count": len(final_decision.decisions),
        "finding_count": len(final_decision.findings),
        "blocking_finding_count": blocking_finding_count,
        "routing_counts": dict(sorted(routing_counts.items())),
        "routing_category_counts": dict(sorted(routing_counts.items())),
        "routing_distribution_percent": _routing_distribution_percent(
            routing_counts=routing_counts,
            total_candidates=total_candidates,
        ),
        "exception_candidate_count": manual_review_count,
        "exception_rate_percent": _percentage(
            numerator=manual_review_count,
            denominator=total_candidates,
        ),
        "candidates_with_compliance_flags": compliance_flag_count,
        "compliance_flag_rate_percent": _percentage(
            numerator=compliance_flag_count,
            denominator=total_candidates,
        ),
        "candidates_with_credential_issues": credential_issue_count,
        "credential_issue_rate_percent": _percentage(
            numerator=credential_issue_count,
            denominator=total_candidates,
        ),
        "candidates_with_anomalies": anomaly_count,
        "anomaly_rate_percent": _percentage(
            numerator=anomaly_count,
            denominator=total_candidates,
        ),
        "manual_review_rate_percent": _percentage(
            numerator=manual_review_count,
            denominator=total_candidates,
        ),
        "avg_confidence_for_manual_review": _percentage(
            numerator=manual_review_count,
            denominator=total_candidates,
        ),
        "artifacts_created": sorted(
            {
                *existing_metrics.get("artifacts_created", []),
                "artifacts/final_decision.json",
                "artifacts/shortlist.csv",
                "artifacts/hiring_packet.json",
                "artifacts/metrics.json",
                "artifacts/audit_log.md",
            }
        ),
        "deterministic": True,
        "requires_human_approval": True,
        "final_hiring_decision_made_by_system": False,
        "notes": [
            "Metrics summarize local deterministic demo outputs only.",
            "Routing is decision support; human approval remains required.",
        ],
    }

    return write_json_artifact(
        scaffold=scaffold,
        artifact_key="metrics",
        payload=payload,
        mark_created=False,
    )


def write_audit_log(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
    context: BundleContext | None = None,
) -> Path:
    """Write a human-readable final audit summary for the run."""

    path = artifact_path(scaffold, "audit_log")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        _build_audit_log_markdown(
            scaffold=scaffold,
            final_decision=final_decision,
            context=context,
        ),
        encoding="utf-8",
    )
    return path


def mark_final_artifacts_created(scaffold: RunScaffold) -> None:
    """Mark all Task 5 artifacts as created in artifact_manifest.json."""

    mark_artifacts_created(
        scaffold=scaffold,
        artifact_keys=FINAL_ARTIFACT_KEYS,
    )


def _read_optional_context(scaffold: RunScaffold) -> BundleContext | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="context_packet")
    return BundleContext.model_validate(payload) if payload is not None else None


def _read_optional_candidate_profile(scaffold: RunScaffold) -> CandidateProfile | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="candidate_profile")
    return CandidateProfile.model_validate(payload) if payload is not None else None


def _read_optional_match_results(scaffold: RunScaffold) -> MatchResultsArtifact | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="match_scores")
    return MatchResultsArtifact.model_validate(payload) if payload is not None else None


def _ordered_shortlist_decisions(
    decisions: list[CandidateRoutingDecision],
) -> list[CandidateRoutingDecision]:
    return sorted(
        decisions,
        key=lambda decision: (
            _ROUTE_RANK.get(decision.routing_category, 99),
            -(decision.score if decision.score is not None else -1.0),
            decision.candidate_id,
            decision.application_id,
        ),
    )


def _ordered_decisions(
    decisions: list[CandidateRoutingDecision],
) -> list[CandidateRoutingDecision]:
    return sorted(decisions, key=lambda item: (item.candidate_id, item.application_id))


def _format_score(score: float | None) -> str:
    return "" if score is None else f"{score:.2f}"


def _job_summary(context: BundleContext | None) -> dict[str, str | None]:
    if context is None:
        return {"job_id": None, "title": None, "department": None, "location": None}

    return {
        "job_id": context.job.id,
        "title": context.job.title,
        "department": context.job.department,
        "location": context.job.location,
    }


def _candidate_packet_summary(
    *,
    decision: CandidateRoutingDecision,
    context: BundleContext | None,
    candidate_profile: CandidateProfile | None,
    candidate_profiles: list[CandidateProfile],
    match_results: MatchResultsArtifact | None,
) -> dict[str, Any]:
    candidate = _candidate_lookup(context).get(
        (decision.candidate_id, decision.application_id)
    )
    match = _match_lookup(match_results).get(decision.application_id)

    return {
        "candidate_id": decision.candidate_id,
        "application_id": decision.application_id,
        "candidate_name": _candidate_name(
            _profile_lookup(candidate_profile, candidate_profiles).get(
                (decision.candidate_id, decision.application_id)
            ),
            candidate,
        ),
        "routing_recommendation": decision.routing_category.value,
        "routing_reason": decision.reason,
        "score": decision.score,
        "requires_human_approval": decision.requires_human_approval,
        "blocking_finding_ids": sorted(decision.blocking_finding_ids),
        "profile_reference": "artifacts/candidate_profile.json",
        "match_score_reference": "artifacts/match_scores.json",
        "findings_reference": "artifacts/final_decision.json#findings",
        "match_recommendation_signal": match.recommendation_signal if match else None,
        "final_hiring_decision_made_by_system": False,
    }


def _candidate_lookup(
    context: BundleContext | None,
) -> dict[tuple[str, str], Any]:
    if context is None:
        return {}

    return {
        (candidate.id, candidate.application_id): candidate
        for candidate in context.candidates
    }


def _match_lookup(
    match_results: MatchResultsArtifact | None,
) -> dict[str, Any]:
    if match_results is None:
        return {}

    return {result.application_id: result for result in match_results.results}


def _profile_lookup(
    candidate_profile: CandidateProfile | None,
    candidate_profiles: list[CandidateProfile],
) -> dict[tuple[str, str], CandidateProfile]:
    profiles = list(candidate_profiles)
    if candidate_profile is not None:
        profiles.append(candidate_profile)

    return {
        (profile.candidate_id, profile.application_id): profile
        for profile in profiles
    }


def _candidate_name(
    candidate_profile: CandidateProfile | None,
    candidate: Any | None,
) -> str | None:
    if candidate_profile is not None and candidate_profile.full_name.value:
        return candidate_profile.full_name.value

    if candidate is not None:
        return candidate.name

    return None


def _build_audit_log_markdown(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact,
    context: BundleContext | None,
) -> str:
    routing_lines = "\n".join(
        _render_decision_line(decision)
        for decision in _ordered_shortlist_decisions(final_decision.decisions)
    )
    finding_lines = "\n".join(
        _render_finding_line(finding)
        for finding in sorted(
            final_decision.findings,
            key=lambda item: (
                _SEVERITY_RANK[item.severity],
                item.candidate_id or "",
                item.application_id or "",
                item.id,
            ),
        )[:10]
    )

    if not routing_lines:
        routing_lines = "- No candidate routing decisions were generated."

    if not finding_lines:
        finding_lines = "- No important findings were generated."

    candidate_count = len(context.candidates) if context else len(final_decision.decisions)

    return (
        "# ICSHPS Audit Log\n\n"
        "## Run Summary\n\n"
        f"- Run ID: `{scaffold.run_id}`\n"
        f"- Bundle ID: `{final_decision.bundle_id}`\n"
        f"- Scenario type: `{final_decision.scenario_type}`\n"
        f"- Candidate count: `{candidate_count}`\n"
        f"- Unified finding count: `{len(final_decision.findings)}`\n"
        "- Deterministic run: `true`\n"
        "- Final hiring decision made by system: `false`\n\n"
        "## Pipeline Stages Completed\n\n"
        "1. Hiring Bundle scaffold and manifest snapshot\n"
        "2. Application intake and context packet\n"
        "3. Candidate profile extraction artifact consumption\n"
        "4. Match score artifact consumption\n"
        "5. Verification, compliance, and anomaly finding consumption\n"
        "6. Unified findings, deduplication, routing, and final artifact generation\n\n"
        "## Artifacts Generated\n\n"
        "- `artifacts/final_decision.json`\n"
        "- `artifacts/shortlist.csv`\n"
        "- `artifacts/hiring_packet.json`\n"
        "- `artifacts/metrics.json`\n"
        "- `artifacts/audit_log.md`\n\n"
        "## Candidate Routing Summary\n\n"
        f"{routing_lines}\n\n"
        "## Important Findings\n\n"
        f"{finding_lines}\n\n"
        "## V2 Optional Feature Status\n\n"
        "- LLM-assisted extraction: `not enabled by default`.\n"
        "- Scanned resume detection: `not generated in this run`.\n"
        "- Interview scheduling artifact: "
        f"`{_optional_artifact_status(scaffold, 'interview_schedule')}`.\n"
        "- Fraud findings artifact: "
        f"`{_optional_artifact_status(scaffold, 'fraud_findings')}`.\n"
        "- ATS mock payload: "
        f"`{_optional_artifact_status(scaffold, 'ats_payload')}`.\n"
        "- Real external integrations: `not used`.\n\n"
        "Interview scheduling, when generated, uses Google Calendar availability "
        "lookup only. It does not create calendar events or send invitations.\n\n"
        "## Human Approval Reminder\n\n"
        "ICSHPS is a local decision-support MVP. It does not make final hiring, "
        "rejection, interview, HRIS, ATS, LinkedIn, background-check, email, or "
        "calendar actions. Every recommendation requires human approval.\n"
    )


def _v2_metric_values(scaffold: RunScaffold) -> dict[str, Any]:
    existing = read_json_artifact(scaffold=scaffold, artifact_key="metrics") or {}
    return {
        key: existing.get(key, default)
        for key, default in V2_METRIC_DEFAULTS.items()
    }


def _optional_artifact_status(scaffold: RunScaffold, artifact_key: str) -> str:
    path = artifact_path(scaffold, artifact_key)
    return "generated" if path.exists() else "not generated"


def _render_decision_line(decision: CandidateRoutingDecision) -> str:
    score = _format_score(decision.score) or "not available"
    blockers = ", ".join(sorted(decision.blocking_finding_ids)) or "none"
    return (
        f"- `{decision.candidate_id}` / `{decision.application_id}`: "
        f"{decision.routing_category.value}; score: `{score}`; "
        f"blocking findings: `{blockers}`; human approval required: "
        f"`{str(decision.requires_human_approval).lower()}`. "
        f"Reason: {decision.reason}"
    )


def _render_finding_line(finding: Any) -> str:
    candidate = finding.candidate_id or "run-level"
    application = finding.application_id or "run-level"
    return (
        f"- `{finding.id}` [{finding.severity.value}] "
        f"{finding.title} — candidate: `{candidate}`, application: `{application}`"
    )


def _is_manual_review_routing(category: RoutingCategory) -> bool:
    return category in {
        RoutingCategory.MANUAL_REVIEW,
        RoutingCategory.CREDENTIAL_VERIFICATION_PENDING,
        RoutingCategory.EMPLOYMENT_HISTORY_INCONSISTENCY,
        RoutingCategory.DUPLICATE_MULTI_ROLE_REVIEW,
        RoutingCategory.EEO_COMPLIANCE_REVIEW,
        RoutingCategory.RECOMMENDED_REJECTION_HUMAN_APPROVAL,
    }


def _percentage(*, numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round((numerator / denominator) * 100.0, 2)


def _routing_distribution_percent(
    *,
    routing_counts: Counter[str],
    total_candidates: int,
) -> dict[str, float]:
    return {
        category: _percentage(numerator=count, denominator=total_candidates)
        for category, count in sorted(routing_counts.items())
    }


def _candidate_count_with_category(
    *,
    final_decision: FinalDecisionArtifact,
    categories: set[str],
    title_tokens: tuple[str, ...] = (),
) -> int:
    candidate_ids: set[str] = set()

    for finding in final_decision.findings:
        category = finding.category.value
        title = (finding.title or "").lower()
        if category not in categories:
            continue
        if title_tokens and not any(token in title for token in title_tokens):
            continue
        if finding.candidate_id:
            candidate_ids.add(finding.candidate_id)

    return len(candidate_ids)
