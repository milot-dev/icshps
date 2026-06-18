from __future__ import annotations

from icshps.schemas import (
    CandidateMatchResult,
    JobMatchRequirements,
    RequirementCheck,
    CandidateProfile,
    CertificationRecord,
    SkillRecord,
)
from icshps.utils.text import normalize_token_text

MUST_HAVE_WEIGHT = 45.0
NICE_TO_HAVE_WEIGHT = 25.0
EXPERIENCE_WEIGHT = 15.0
CERTIFICATION_WEIGHT = 15.0
MISSING_MANDATORY_SCORE_CAP = 69.0


def match_candidate_to_job(
    candidate_profile: CandidateProfile,
    job_requirements: JobMatchRequirements,
) -> CandidateMatchResult:
    """Compare one candidate profile against typed job requirements."""

    skills_by_name = _skills_by_normalized_name(candidate_profile.skills)
    certifications_by_name = _certifications_by_normalized_name(
        candidate_profile.certifications
    )

    must_have_results = _check_requirements(
        requirements=job_requirements.must_have,
        available=skills_by_name,
        required=True,
    )
    nice_to_have_results = _check_requirements(
        requirements=job_requirements.nice_to_have,
        available=skills_by_name,
        required=False,
    )
    certification_results = _check_requirements(
        requirements=job_requirements.mandatory_certifications,
        available=certifications_by_name,
        required=True,
        requirement_prefix="certification",
    )

    missing_mandatory_requirements = [
        result.label
        for result in [*must_have_results, *certification_results]
        if not result.satisfied
    ]

    score = _calculate_score(
        must_have_score=_requirement_group_score(must_have_results),
        nice_to_have_score=_requirement_group_score(nice_to_have_results),
        experience_score=_experience_score(
            candidate_profile=candidate_profile,
            minimum_years_experience=job_requirements.minimum_years_experience,
        ),
        certification_score=_requirement_group_score(certification_results),
    )

    if missing_mandatory_requirements:
        score = min(score, MISSING_MANDATORY_SCORE_CAP)

    return CandidateMatchResult(
        candidate_id=candidate_profile.candidate_id,
        application_id=candidate_profile.application_id,
        job_id=job_requirements.job_id,
        score=round(score, 2),
        must_have_results=must_have_results,
        nice_to_have_results=nice_to_have_results,
        missing_mandatory_requirements=missing_mandatory_requirements,
        recommendation_signal=_recommendation_signal(
            score=score,
            missing_mandatory_requirements=missing_mandatory_requirements,
        ),
    )


def _check_requirements(
    *,
    requirements: list[str],
    available: dict[str, SkillRecord | CertificationRecord],
    required: bool,
    requirement_prefix: str | None = None,
) -> list[RequirementCheck]:
    results: list[RequirementCheck] = []

    for index, requirement in enumerate(requirements, start=1):
        normalized_requirement = _normalize(requirement)
        matched_record = available.get(normalized_requirement)
        label = (
            f"{requirement_prefix}: {requirement}"
            if requirement_prefix is not None
            else requirement
        )
        results.append(
            RequirementCheck(
                requirement_id=_requirement_id(
                    prefix=requirement_prefix or "requirement",
                    index=index,
                    requirement=requirement,
                ),
                label=label,
                required=required,
                satisfied=matched_record is not None,
                explanation=_requirement_explanation(
                    requirement=requirement,
                    matched=matched_record is not None,
                    required=required,
                    requirement_prefix=requirement_prefix,
                ),
                evidence=matched_record.evidence if matched_record is not None else [],
            )
        )

    return results


def _skills_by_normalized_name(skills: list[SkillRecord]) -> dict[str, SkillRecord]:
    return {
        _normalize(skill.normalized_name or skill.name): skill
        for skill in skills
        if _normalize(skill.normalized_name or skill.name)
    }


def _certifications_by_normalized_name(
    certifications: list[CertificationRecord],
) -> dict[str, CertificationRecord]:
    return {
        _normalize(certification.name): certification
        for certification in certifications
        if _normalize(certification.name)
    }


def _normalize(value: str) -> str:
    return normalize_token_text(value).replace(" ", "")


def _requirement_id(*, prefix: str, index: int, requirement: str) -> str:
    normalized = _normalize(requirement)
    suffix = normalized or f"{index:03d}"
    return f"{prefix}-{index:03d}-{suffix}"


def _requirement_explanation(
    *,
    requirement: str,
    matched: bool,
    required: bool,
    requirement_prefix: str | None,
) -> str:
    requirement_type = "certification" if requirement_prefix else "skill"
    priority = "required" if required else "nice-to-have"
    if matched:
        return f"Matched {priority} {requirement_type}: {requirement}."
    return f"Missing {priority} {requirement_type}: {requirement}."


def _requirement_group_score(results: list[RequirementCheck]) -> float:
    if not results:
        return 100.0

    satisfied_count = sum(1 for result in results if result.satisfied)
    return (satisfied_count / len(results)) * 100.0


def _experience_score(
    *,
    candidate_profile: CandidateProfile,
    minimum_years_experience: float | None,
) -> float:
    if minimum_years_experience is None:
        return 100.0

    candidate_years = (
        candidate_profile.relevant_years_experience_estimate
        if candidate_profile.relevant_years_experience_estimate is not None
        else candidate_profile.total_years_experience_estimate
    )
    if candidate_years is None:
        return 0.0

    return 100.0 if candidate_years >= minimum_years_experience else 0.0


def _calculate_score(
    *,
    must_have_score: float,
    nice_to_have_score: float,
    experience_score: float,
    certification_score: float,
) -> float:
    return (
        (must_have_score * MUST_HAVE_WEIGHT)
        + (nice_to_have_score * NICE_TO_HAVE_WEIGHT)
        + (experience_score * EXPERIENCE_WEIGHT)
        + (certification_score * CERTIFICATION_WEIGHT)
    ) / 100.0


def _recommendation_signal(
    *,
    score: float,
    missing_mandatory_requirements: list[str],
) -> str:
    if score >= 80.0 and not missing_mandatory_requirements:
        return "strong_match"
    if score >= 60.0 or missing_mandatory_requirements:
        return "partial_match"
    return "weak_match"
