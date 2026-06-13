from icshps.agents.extraction.candidate_profile_extractor import extract_candidate_profile
from icshps.schemas.profile import CandidateProfile


SAMPLE_RESUME_TEXT = """
Jane Doe
Prishtina, Kosovo
jane.doe@example.com | +383 44 123 456
https://www.linkedin.com/in/janedoe

Skills
Python, SQL, FastAPI, LangGraph, Docker, Git, Machine Learning

Education
University of Prishtina - Bachelor in Computer Engineering, Kosovo, 2023

Certifications
AWS Certified Cloud Practitioner by Amazon, issued 2025, Credential ID: AWS-123

Work Experience
AI Engineering Intern at Example AI Lab - Jun 2025 to Sep 2025
- Built deterministic resume extraction utilities
- Tested candidate profile JSON outputs
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
    assert profile.synthetic_fallback_used is False
    assert profile.full_name.value == "Jane Doe"
    assert profile.email.value == "jane.doe@example.com"
    assert profile.phone.value == "+383 44 123 456"
    assert profile.location.value == "Prishtina, Kosovo"
    assert profile.linkedin_url.value == "https://www.linkedin.com/in/janedoe"


def test_extract_candidate_profile_extracts_sections():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    skill_names = {skill.name for skill in profile.skills}

    assert {
        "Python",
        "SQL",
        "FastAPI",
        "LangGraph",
        "Docker",
        "Git",
        "Machine Learning",
    }.issubset(skill_names)

    assert profile.education[0].institution == "University of Prishtina"
    assert profile.education[0].degree == "Bachelor"
    assert profile.certifications[0].name.startswith(
        "AWS Certified Cloud Practitioner")
    assert profile.employment_history[0].company == "Example AI Lab"
    assert profile.employment_history[0].title == "AI Engineering Intern"
    assert profile.employment_history[0].responsibilities


def test_extract_candidate_profile_handles_incomplete_resume_gracefully():
    profile = extract_candidate_profile(
        "Alex Smith\nPython\nSQL",
        candidate_id="cand_002",
        application_id="app_002",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.full_name.value == "Alex Smith"
    assert profile.email is None
    assert profile.phone is None
    assert profile.education == []
    assert profile.employment_history == []
    assert profile.manual_review_flags

    assert {error.code for error in profile.extraction_errors} >= {
        "MISSING_CONTACT_INFO",
        "MISSING_EDUCATION",
        "MISSING_EMPLOYMENT_HISTORY",
    }


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
