from icshps.agents.extraction import candidate_profile_extractor
from icshps.agents.extraction.candidate_profile_extractor import (
    dedupe_evidence_refs,
    extract_candidate_profile,
    has_extracted_values_missing_evidence,
)
from icshps.schemas.common import EvidenceRef
from icshps.schemas.profile import CandidateProfile, ExtractedField, SkillRecord


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
    assert profile.section_confidence_bands == {
        "contact": "high",
        "skills": "high",
        "employment_history": "low",
        "education": "low",
        "certifications": "low",
    }
    assert profile.extraction_confidence == 0.8
    assert profile.extraction_confidence_band == "high"


def test_extract_candidate_profile_adds_field_level_evidence():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.full_name.evidence[0].section == "contact"
    assert profile.full_name.evidence[0].text_snippet == "Jane Doe"
    assert profile.email.evidence[0].text_snippet == "jane.doe@example.com"
    assert profile.phone.evidence[0].text_snippet == "+383 44 123 456"
    assert profile.location.evidence[0].text_snippet == "Prishtina, Kosovo"
    assert all(skill.evidence for skill in profile.skills)


def test_extract_candidate_profile_adds_deterministic_evidence_ids_and_field_paths():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.full_name.evidence[0].evidence_id == "ev_contact_full_name_001"
    assert profile.full_name.evidence[0].field_path == "full_name"
    assert profile.email.evidence[0].evidence_id == "ev_contact_email_001"
    assert profile.email.evidence[0].field_path == "email"
    assert profile.phone.evidence[0].evidence_id == "ev_contact_phone_001"
    assert profile.phone.evidence[0].field_path == "phone"
    assert profile.skills[0].evidence[0].evidence_id == "ev_skill_python_001"
    assert profile.skills[0].evidence[0].field_path == "skills[0]"


def test_extract_candidate_profile_builds_central_evidence_index():
    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    snippets = [evidence.text_snippet for evidence in profile.evidence_index]

    assert snippets[:4] == [
        "Jane Doe",
        "jane.doe@example.com",
        "+383 44 123 456",
        "Prishtina, Kosovo",
    ]
    assert "Python" in snippets
    assert "SQL" in snippets
    assert len(snippets) == len(set(snippets))
    assert all(evidence.evidence_id for evidence in profile.evidence_index)
    assert all(evidence.field_path for evidence in profile.evidence_index)


def test_evidence_index_deduplicates_by_evidence_id():
    first = EvidenceRef(
        evidence_id="ev_contact_email_001",
        field_path="email",
        source_path="resume.txt",
        source_type="resume_text",
        section="contact",
        text_snippet="jane.doe@example.com",
        confidence=0.95,
    )
    duplicate = EvidenceRef(
        evidence_id="ev_contact_email_001",
        field_path="email",
        source_path="resume.txt",
        source_type="resume_text",
        section="contact",
        text_snippet="jane.doe@example.com",
        confidence=0.95,
    )

    assert dedupe_evidence_refs([first, duplicate]) == [first]


def test_missing_evidence_on_extracted_value_is_detected():
    assert has_extracted_values_missing_evidence(
        full_name=ExtractedField(value="Jane Doe", confidence=0.8, evidence=[]),
        email=None,
        phone=None,
        location=None,
        skills=[],
    ) is True

    assert has_extracted_values_missing_evidence(
        full_name=ExtractedField(value="Jane Doe", confidence=0.8),
        email=None,
        phone=None,
        location=None,
        skills=[
            SkillRecord(
                name="Python",
                normalized_name="python",
                confidence=0.8,
                evidence=[],
            )
        ],
    ) is True


def test_missing_evidence_on_extracted_value_adds_review_flag(monkeypatch):
    def extract_name_without_evidence(lines, source_path):
        return ExtractedField(value="Jane Doe", confidence=0.8, evidence=[])

    monkeypatch.setattr(
        candidate_profile_extractor,
        "extract_full_name",
        extract_name_without_evidence,
    )

    profile = candidate_profile_extractor.extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert (
        "Some extracted fields are missing evidence; manual review recommended."
        in profile.manual_review_flags
    )


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
    assert profile.section_confidence_bands["contact"] == "low"
    assert profile.section_confidence_bands["skills"] == "high"
    assert profile.extraction_confidence_band == "low"
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
    assert profile.extraction_confidence_band == "low"
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
