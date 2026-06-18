from pathlib import Path

from icshps.agents.matching import match_candidate_to_job
from icshps.schemas.common import EvidenceRef
from icshps.schemas.matching import CandidateMatchResult, JobMatchRequirements
from icshps.schemas.profile import (
    CandidateProfile,
    CertificationRecord,
    ExtractedField,
    SkillRecord,
)


def test_match_candidate_to_job_returns_strong_match_when_all_requirements_match():
    profile = build_candidate_profile(
        skills=["Python", "SQL", "Docker"],
        certifications=["AWS Certified Developer"],
        relevant_years=4.0,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["Python", "SQL"],
        nice_to_have=["Docker"],
        minimum_years_experience=3.0,
        mandatory_certifications=["AWS Certified Developer"],
    )

    result = match_candidate_to_job(profile, requirements)

    assert isinstance(result, CandidateMatchResult)
    assert result.candidate_id == "candidate_001"
    assert result.application_id == "app_001"
    assert result.job_id == "job_001"
    assert result.score == 100.0
    assert result.recommendation_signal == "strong_match"
    assert result.missing_mandatory_requirements == []
    assert all(check.satisfied for check in result.must_have_results)
    assert all(check.satisfied for check in result.nice_to_have_results)


def test_missing_must_have_applies_soft_cap_and_records_missing_requirement():
    profile = build_candidate_profile(
        skills=["Python", "SQL", "Docker"],
        certifications=[],
        relevant_years=4.0,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["Python", "SQL", "Rust"],
        nice_to_have=["Docker"],
        minimum_years_experience=3.0,
    )

    result = match_candidate_to_job(profile, requirements)

    assert result.score == 69.0
    assert result.recommendation_signal == "partial_match"
    assert result.missing_mandatory_requirements == ["Rust"]
    assert [check.satisfied for check in result.must_have_results] == [
        True,
        True,
        False,
    ]


def test_missing_mandatory_certification_uses_existing_missing_list():
    profile = build_candidate_profile(
        skills=["Python"],
        certifications=[],
        relevant_years=4.0,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["Python"],
        mandatory_certifications=["AWS Certified Developer"],
    )

    result = match_candidate_to_job(profile, requirements)

    assert result.score == 69.0
    assert result.recommendation_signal == "partial_match"
    assert result.missing_mandatory_requirements == [
        "certification: AWS Certified Developer"
    ]


def test_missing_experience_estimate_scores_zero_when_minimum_years_required():
    profile = build_candidate_profile(
        skills=["Python"],
        certifications=[],
        relevant_years=None,
        total_years=None,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["Python"],
        minimum_years_experience=3.0,
    )

    result = match_candidate_to_job(profile, requirements)

    assert result.score == 85.0
    assert result.recommendation_signal == "strong_match"


def test_empty_requirement_categories_get_full_credit():
    profile = build_candidate_profile(
        skills=[],
        certifications=[],
        relevant_years=None,
    )
    requirements = JobMatchRequirements(job_id="job_001")

    result = match_candidate_to_job(profile, requirements)

    assert result.score == 100.0
    assert result.recommendation_signal == "strong_match"
    assert result.must_have_results == []
    assert result.nice_to_have_results == []
    assert result.missing_mandatory_requirements == []


def test_matched_requirements_include_structured_evidence():
    profile = build_candidate_profile(
        skills=["FastAPI"],
        certifications=[],
        relevant_years=None,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["fast api"],
    )

    result = match_candidate_to_job(profile, requirements)

    assert result.must_have_results[0].satisfied is True
    assert result.must_have_results[0].evidence[0].source_path == Path("resume.txt")
    assert result.must_have_results[0].evidence[0].section == "skills"
    assert result.must_have_results[0].evidence[0].text_snippet == "FastAPI"


def test_match_candidate_to_job_is_deterministic():
    profile = build_candidate_profile(
        skills=["Python", "SQL"],
        certifications=["AWS Certified Developer"],
        relevant_years=5.0,
    )
    requirements = JobMatchRequirements(
        job_id="job_001",
        must_have=["Python", "SQL"],
        nice_to_have=["Docker"],
        minimum_years_experience=3.0,
        mandatory_certifications=["AWS Certified Developer"],
    )

    first = match_candidate_to_job(profile, requirements)
    second = match_candidate_to_job(profile, requirements)

    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def build_candidate_profile(
    *,
    skills: list[str],
    certifications: list[str],
    relevant_years: float | None,
    total_years: float | None = None,
) -> CandidateProfile:
    return CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="role_001",
        source_file="resume.txt",
        full_name=ExtractedField(value="Jane Doe", confidence=0.9),
        email=ExtractedField(value="jane@example.com", confidence=0.9),
        phone=None,
        location=None,
        skills=[build_skill(name) for name in skills],
        certifications=[build_certification(name) for name in certifications],
        total_years_experience_estimate=total_years,
        relevant_years_experience_estimate=relevant_years,
        extraction_confidence=0.8,
        section_confidence={},
        evidence_index=[],
        manual_review_flags=[],
        synthetic_fallback_used=False,
        extraction_errors=[],
    )


def build_skill(name: str) -> SkillRecord:
    return SkillRecord(
        name=name,
        normalized_name=name.lower(),
        confidence=0.9,
        evidence=[
            EvidenceRef(
                source_path=Path("resume.txt"),
                source_type="resume_text",
                section="skills",
                text_snippet=name,
                confidence=0.9,
            )
        ],
    )


def build_certification(name: str) -> CertificationRecord:
    return CertificationRecord(
        name=name,
        issuer=None,
        confidence=0.9,
        evidence=[
            EvidenceRef(
                source_path=Path("resume.txt"),
                source_type="resume_text",
                section="certifications",
                text_snippet=name,
                confidence=0.9,
            )
        ],
    )
