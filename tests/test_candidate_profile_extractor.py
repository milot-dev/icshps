from icshps.agents.extraction.candidate_profile_extractor import extract_candidate_profile
from icshps.schemas.profile import CandidateProfile


SAMPLE_RESUME_TEXT = """
Jane Doe
Prishtina, Kosovo
jane.doe@example.com | +383 44 123 456

Skills
Python, SQL, FastAPI, LangGraph, Docker, Git, Machine Learning
"""


def test_extract_candidate_profile_returns_schema_valid_profile():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert isinstance(profile, CandidateProfile)
    assert profile.candidate_id == "cand_001"
    assert profile.application_id == "app_001"
    assert profile.role_id == "ai_engineer_intern"
    assert profile.synthetic_fallback_used is False


def test_extract_candidate_profile_extracts_basic_fields_and_skills():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    skill_names = {skill.name for skill in profile.skills}

    assert profile.full_name.value == "Jane Doe"
    assert profile.email.value == "jane.doe@example.com"
    assert profile.phone.value == "+383 44 123 456"
    assert profile.location.value == "Prishtina, Kosovo"
    assert {"Python", "SQL", "FastAPI", "LangGraph"}.issubset(skill_names)
    assert profile.education == []
    assert profile.employment_history == []
    assert profile.certifications == []


def test_extract_candidate_profile_calculates_confidence_scores():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.full_name.confidence == 0.8
    assert profile.email.confidence == 0.95
    assert profile.phone.confidence == 0.85
    assert profile.location.confidence == 0.6
    assert profile.section_confidence == {
        "contact": 0.8,
        "skills": 0.8,
        "employment_history": 0.0,
        "education": 0.0,
        "certifications": 0.0,
    }
    assert profile.extraction_confidence == 0.8


def test_extract_candidate_profile_flags_low_confidence_profile():
    profile = extract_candidate_profile(
        "Jane Doe\nPython",
        candidate_id="cand_low_confidence",
        application_id="app_low_confidence",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.synthetic_fallback_used is False
    assert profile.section_confidence["contact"] == 0.2
    assert profile.section_confidence["skills"] == 0.8
    assert profile.extraction_confidence == 0.38
    assert "No email or phone number was detected." in profile.manual_review_flags
    assert (
        "Low extraction confidence; manual review recommended."
        in profile.manual_review_flags
    )


def test_extract_candidate_profile_uses_fallback_for_empty_text():
    profile = extract_candidate_profile(
        "",
        candidate_id="cand_empty",
        application_id="app_empty",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.synthetic_fallback_used is True
    assert profile.full_name.value == "Unknown Candidate"
    assert profile.extraction_errors[0].code == "SYNTHETIC_FALLBACK_USED"


def test_extract_candidate_profile_uses_fallback_when_name_is_missing():
    profile = extract_candidate_profile(
        "jane.doe@example.com\nPython\nSQL",
        candidate_id="cand_missing_name",
        application_id="app_missing_name",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.synthetic_fallback_used is True
    assert profile.full_name.value == "Unknown Candidate"
    assert "Required candidate name" in profile.manual_review_flags[1]


def test_extract_candidate_profile_is_deterministic():
    profile_1 = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    profile_2 = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile_1.model_dump() == profile_2.model_dump()
