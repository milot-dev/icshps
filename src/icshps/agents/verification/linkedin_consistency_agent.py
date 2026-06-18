from __future__ import annotations

from pathlib import Path
from typing import Any

from icshps.schemas import (
    CandidateProfile,
    EmploymentRecord,
    EvidenceRef,
    Finding,
    FindingCategory,
    FindingsArtifact,
    Severity,
)
from icshps.utils.file_io import read_yaml_object
from icshps.utils.dates import month_index
from icshps.utils.text import normalize_lookup_key

AGENT_NAME = "linkedin_consistency_agent_v1"


def build_linkedin_consistency_findings(
    *,
    run_id: str,
    candidate_profile: CandidateProfile,
    linkedin_profiles_path: Path | None,
) -> FindingsArtifact:
    """Compare resume employment history to Hiring Bundle mock LinkedIn data."""

    linkedin_positions = _linkedin_positions_for_candidate(
        linkedin_profiles_path=linkedin_profiles_path,
        candidate_id=candidate_profile.candidate_id,
    )
    findings: list[Finding] = []

    for employment in candidate_profile.employment_history:
        position = _matching_position(employment, linkedin_positions)
        if position is None:
            continue

        if _date_range(employment) != _position_date_range(position):
            findings.append(
                _finding(
                    candidate_profile=candidate_profile,
                    employment=employment,
                    linkedin_profiles_path=linkedin_profiles_path,
                    position=position,
                    finding_id=f"linkedin-date-contradiction-{len(findings) + 1:03d}",
                    title="Resume employment dates contradict mock LinkedIn profile",
                    reason="Employment date contradictions require manual review.",
                )
            )

        linkedin_title = str(position.get("title", "")).strip()
        if linkedin_title and employment.title:
            if _normalize(linkedin_title) != _normalize(employment.title):
                findings.append(
                    _finding(
                        candidate_profile=candidate_profile,
                        employment=employment,
                        linkedin_profiles_path=linkedin_profiles_path,
                        position=position,
                        finding_id=f"linkedin-title-discrepancy-{len(findings) + 1:03d}",
                        title="Resume job title differs from mock LinkedIn profile",
                        reason="Job title discrepancies require manual review.",
                    )
                )

    findings.extend(
        _chronology_findings(
            candidate_profile=candidate_profile,
            starting_index=len(findings) + 1,
        )
    )

    return FindingsArtifact(run_id=run_id, findings=findings)


def _linkedin_positions_for_candidate(
    *,
    linkedin_profiles_path: Path | None,
    candidate_id: str,
) -> list[dict[str, Any]]:
    if (
        linkedin_profiles_path is None
        or not linkedin_profiles_path.exists()
        or linkedin_profiles_path.stat().st_size == 0
    ):
        return []

    payload = read_yaml_object(linkedin_profiles_path)

    if str(payload.get("candidate_id", "")) == candidate_id:
        return _positions_from(payload)

    for candidate in payload.get("candidates", []):
        if (
            isinstance(candidate, dict)
            and str(candidate.get("candidate_id", "")) == candidate_id
        ):
            return _positions_from(candidate)

    return []


def _positions_from(payload: dict[str, Any]) -> list[dict[str, Any]]:
    positions = payload.get("linkedin_profile") or payload.get("positions") or []
    return [position for position in positions if isinstance(position, dict)]


def _matching_position(
    employment: EmploymentRecord,
    positions: list[dict[str, Any]],
) -> dict[str, Any] | None:
    company = _normalize(employment.company)
    for position in positions:
        if _normalize(str(position.get("company", ""))) == company:
            return position
    return None


def _finding(
    *,
    candidate_profile: CandidateProfile,
    employment: EmploymentRecord,
    linkedin_profiles_path: Path | None,
    position: dict[str, Any],
    finding_id: str,
    title: str,
    reason: str,
) -> Finding:
    return Finding(
        id=finding_id,
        source_agent=AGENT_NAME,
        category=FindingCategory.LINKEDIN_CONSISTENCY,
        severity=Severity.WARNING,
        title=title,
        description=f"Resume role at '{employment.company}' differs from mock LinkedIn data.",
        reason=reason,
        candidate_id=candidate_profile.candidate_id,
        application_id=candidate_profile.application_id,
        confidence=1.0,
        evidence=[
            *employment.evidence,
            EvidenceRef(
                source_path=linkedin_profiles_path or Path("mock_linkedin_profile"),
                source_type="mock_linkedin_profile",
                section="linkedin_profile",
                text_snippet=str(position),
                confidence=1.0,
            ),
        ],
        recommendation="Route to employment history inconsistency manual review.",
        requires_human_review=True,
    )


def _chronology_findings(
    *,
    candidate_profile: CandidateProfile,
    starting_index: int,
) -> list[Finding]:
    employments = candidate_profile.employment_history
    findings: list[Finding] = []

    for index, current in enumerate(employments[:-1]):
        next_role = employments[index + 1]
        if (
            month_index(current.start_date) is None
            or month_index(next_role.start_date) is None
        ):
            continue
        if month_index(current.start_date) < month_index(next_role.start_date):
            findings.append(
                Finding(
                    id=f"linkedin-reverse-chronology-{starting_index + len(findings):03d}",
                    source_agent=AGENT_NAME,
                    category=FindingCategory.LINKEDIN_CONSISTENCY,
                    severity=Severity.WARNING,
                    title="Employment history is not reverse chronological",
                    description="Resume employment entries are not ordered from newest to oldest.",
                    reason="Reverse chronology issues require reviewer confirmation.",
                    candidate_id=candidate_profile.candidate_id,
                    application_id=candidate_profile.application_id,
                    confidence=1.0,
                    evidence=[*current.evidence, *next_role.evidence],
                    recommendation="Route to employment history inconsistency manual review.",
                    requires_human_review=True,
                )
            )

    return findings


def _date_range(employment: EmploymentRecord) -> tuple[str | None, str | None]:
    return employment.start_date, employment.end_date


def _position_date_range(position: dict[str, Any]) -> tuple[str | None, str | None]:
    return position.get("start_date"), position.get("end_date")


def _normalize(value: str | None) -> str:
    return normalize_lookup_key(value)
