from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from icshps.schemas.common import EvidenceRef, FindingCategory, Severity
from icshps.schemas.findings import Finding, FindingsArtifact
from icshps.schemas.profile import CandidateProfile, EmploymentRecord

AGENT_NAME = "anomaly_detection_agent_v1"


def build_anomaly_findings(
    *,
    run_id: str,
    candidate_profiles: list[CandidateProfile],
    application_history_path: Path | None = None,
) -> FindingsArtifact:
    """Detect duplicate, multi-role, and employment-overlap anomalies."""

    findings: list[Finding] = []
    findings.extend(_duplicate_profile_findings(candidate_profiles))
    findings.extend(
        _employment_overlap_findings(
            candidate_profiles,
            starting_index=len(findings) + 1,
        )
    )
    findings.extend(
        _multi_role_application_findings(
            application_history_path=application_history_path,
            starting_index=len(findings) + 1,
        )
    )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _duplicate_profile_findings(candidate_profiles: list[CandidateProfile]) -> list[Finding]:
    by_email: dict[str, list[CandidateProfile]] = {}
    for profile in candidate_profiles:
        email = (profile.email.value if profile.email else None) or ""
        if email.strip():
            by_email.setdefault(email.strip().lower(), []).append(profile)

    findings: list[Finding] = []
    for email, profiles in sorted(by_email.items()):
        if len(profiles) < 2:
            continue
        findings.append(
            Finding(
                id=f"anomaly-duplicate-email-{len(findings) + 1:03d}",
                source_agent=AGENT_NAME,
                category=FindingCategory.ANOMALY,
                severity=Severity.WARNING,
                title="Duplicate candidate applications detected",
                description=f"Multiple candidate profiles share email '{email}'.",
                reason="Duplicate emails can indicate repeated or duplicate applications.",
                candidate_id=profiles[0].candidate_id,
                application_id=profiles[0].application_id,
                confidence=1.0,
                evidence=[ref for profile in profiles for ref in profile.evidence_index],
                recommendation="Route to duplicate / multi-role review.",
                requires_human_review=True,
            )
        )
    return findings


def _employment_overlap_findings(
    candidate_profiles: list[CandidateProfile],
    *,
    starting_index: int,
) -> list[Finding]:
    findings: list[Finding] = []
    for profile in candidate_profiles:
        employments = profile.employment_history
        for left_index, left in enumerate(employments):
            for right in employments[left_index + 1 :]:
                if _ranges_overlap(left, right):
                    findings.append(
                        Finding(
                            id=f"anomaly-employment-overlap-{starting_index + len(findings):03d}",
                            source_agent=AGENT_NAME,
                            category=FindingCategory.ANOMALY,
                            severity=Severity.WARNING,
                            title="Overlapping employment history detected",
                            description=(
                                f"Roles at '{left.company}' and '{right.company}' "
                                "have overlapping dates."
                            ),
                            reason="Implausible employment overlaps require manual review.",
                            candidate_id=profile.candidate_id,
                            application_id=profile.application_id,
                            confidence=1.0,
                            evidence=[*left.evidence, *right.evidence],
                            recommendation="Route to employment history inconsistency manual review.",
                            requires_human_review=True,
                        )
                    )
    return findings


def _multi_role_application_findings(
    *,
    application_history_path: Path | None,
    starting_index: int,
) -> list[Finding]:
    if (
        application_history_path is None
        or not application_history_path.exists()
        or application_history_path.stat().st_size == 0
    ):
        return []

    payload = yaml.safe_load(application_history_path.read_text(encoding="utf-8")) or {}
    applications = [item for item in payload.get("applications", []) if isinstance(item, dict)]
    grouped: dict[str, set[str]] = {}
    for application in applications:
        candidate_key = str(
            application.get("candidate_id") or application.get("email") or ""
        ).strip()
        job_id = str(application.get("job_id", "")).strip()
        if candidate_key and job_id:
            grouped.setdefault(candidate_key, set()).add(job_id)

    findings: list[Finding] = []
    for candidate_key, job_ids in sorted(grouped.items()):
        if len(job_ids) < 2:
            continue
        findings.append(
            Finding(
                id=f"anomaly-multi-role-{starting_index + len(findings):03d}",
                source_agent=AGENT_NAME,
                category=FindingCategory.ANOMALY,
                severity=Severity.WARNING,
                title="Candidate applied to multiple roles",
                description=f"Candidate key '{candidate_key}' appears across {len(job_ids)} roles.",
                reason="Same-candidate multi-role activity requires reviewer grouping.",
                candidate_id=candidate_key,
                confidence=1.0,
                evidence=[
                    EvidenceRef(
                        source_path=application_history_path,
                        source_type="mock_application_history",
                        section="applications",
                        text_snippet=", ".join(sorted(job_ids)),
                        confidence=1.0,
                    )
                ],
                recommendation="Route to duplicate / multi-role review.",
                requires_human_review=True,
            )
        )

    return findings


def _ranges_overlap(left: EmploymentRecord, right: EmploymentRecord) -> bool:
    left_start = _month_index(left.start_date)
    left_end = _month_index(left.end_date) if left.end_date else 999999
    right_start = _month_index(right.start_date)
    right_end = _month_index(right.end_date) if right.end_date else 999999

    if None in (left_start, left_end, right_start, right_end):
        return False

    return left_start <= right_end and right_start <= left_end


def _month_index(value: str | None) -> int | None:
    if value is None:
        return None
    parts = value.split("-")
    if len(parts) < 2 or not parts[0].isdigit() or not parts[1].isdigit():
        return None
    return int(parts[0]) * 12 + int(parts[1])
