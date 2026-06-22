import pytest
from pydantic import ValidationError

from icshps.agents.extraction import resume_extraction_agent
from icshps.agents.extraction.llm_recovery import (
    DEFAULT_LLM_EXTRACTION_MAX_TOKENS,
    LLMExtractionRecovery,
    LLMExtractedField,
    LLMSkill,
    llm_recovery_max_tokens,
)
from icshps.agents.extraction.resume_extraction_agent import (
    extract_candidate_profile,
    has_extracted_values_missing_evidence,
    dedupe_evidence_refs
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

SAMPLE_EMPLOYMENT_RESUME_TEXT = """
Alex Morgan
alex.morgan@example.com | +383 44 555 777

Professional Experience
Senior Data Scientist, ByteWorks, May 2022 - Present
Acme Corp - Data Scientist - 2019-08-01 - 2022-03-15
Software Engineer at BuildLabs, 2017 - 2019

Skills
Python, SQL
"""

SAMPLE_EDUCATION_RESUME_TEXT = """
Sam Rivera
sam.rivera@example.com

Education
Bachelor of Science in Computer Science, University of Prishtina, 2018

Skills
Python, SQL
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


def test_extract_candidate_profile_extracts_education_records():
    profile = extract_candidate_profile(
        SAMPLE_EDUCATION_RESUME_TEXT,
        candidate_id="cand_education",
        application_id="app_education",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert len(profile.education) == 1
    education = profile.education[0]
    assert education.degree == "Bachelor of Science in Computer Science"
    assert education.institution == "University of Prishtina"
    assert education.end_year == 2018
    assert education.confidence == 0.78
    assert education.evidence[0].evidence_id == "ev_education_0_record_001"
    assert education.evidence[0].field_path == "education[0]"
    assert education.evidence[0].section == "education"
    assert education.evidence[0] in profile.evidence_index
    assert profile.section_confidence["education"] == 0.78
    assert profile.section_confidence_bands["education"] == "medium"


def test_extract_candidate_profile_extracts_employment_history_records():
    profile = extract_candidate_profile(
        SAMPLE_EMPLOYMENT_RESUME_TEXT,
        candidate_id="cand_employment",
        application_id="app_employment",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert len(profile.employment_history) == 3

    current_role = profile.employment_history[0]
    assert current_role.company == "ByteWorks"
    assert current_role.title == "Senior Data Scientist"
    assert current_role.start_date == "2022-05"
    assert current_role.end_date is None
    assert current_role.is_current is True

    prior_role = profile.employment_history[1]
    assert prior_role.company == "Acme Corp"
    assert prior_role.title == "Data Scientist"
    assert prior_role.start_date == "2019-08-01"
    assert prior_role.end_date == "2022-03-15"
    assert prior_role.is_current is False

    year_only_role = profile.employment_history[2]
    assert year_only_role.company == "BuildLabs"
    assert year_only_role.title == "Software Engineer"
    assert year_only_role.start_date == "2017"
    assert year_only_role.end_date == "2019"


def test_extract_candidate_profile_extracts_inline_employment_record():
    profile = extract_candidate_profile(
        """
Luan Dates
luan.dates@example.com
+383 44 500 500
Employment: DataWorks Backend Engineer, 2021-01 to 2024-03
Skills: Python, FastAPI
""",
        candidate_id="cand_inline_employment",
        application_id="app_inline_employment",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert len(profile.employment_history) == 1
    record = profile.employment_history[0]
    assert record.company == "DataWorks"
    assert record.title == "Backend Engineer"
    assert record.start_date == "2021-01"
    assert record.end_date == "2024-03"


def test_extract_candidate_profile_adds_employment_evidence_to_index():
    profile = extract_candidate_profile(
        SAMPLE_EMPLOYMENT_RESUME_TEXT,
        candidate_id="cand_employment",
        application_id="app_employment",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    employment_evidence = profile.employment_history[0].evidence[0]
    evidence_ids = {evidence.evidence_id for evidence in profile.evidence_index}

    assert employment_evidence.evidence_id == "ev_employment_0_dates_001"
    assert employment_evidence.field_path == "employment_history[0]"
    assert employment_evidence.section == "employment_history"
    assert employment_evidence.evidence_id in evidence_ids


def test_extract_candidate_profile_calculates_employment_section_confidence():
    profile = extract_candidate_profile(
        SAMPLE_EMPLOYMENT_RESUME_TEXT,
        candidate_id="cand_employment",
        application_id="app_employment",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.section_confidence["employment_history"] == 0.8
    assert profile.section_confidence_bands["employment_history"] == "high"


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
        resume_extraction_agent,
        "extract_full_name",
        extract_name_without_evidence,
    )

    profile = resume_extraction_agent.extract_candidate_profile(
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


def test_extract_candidate_profile_uses_fallback_for_too_short_text():
    profile = extract_candidate_profile(
        "Jane Doe",
        candidate_id="cand_short",
        application_id="app_short",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.synthetic_fallback_used is True
    assert profile.full_name.value == "Unknown Candidate"
    assert "too short" in profile.manual_review_flags[1]


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
    assert "Required candidate profile fields" in profile.manual_review_flags[1]


def test_extract_candidate_profile_uses_fallback_when_extraction_fails(monkeypatch):
    def fail_skill_extraction(text, source_path):
        raise RuntimeError("skill parser failed")

    monkeypatch.setattr(
        resume_extraction_agent,
        "extract_skills",
        fail_skill_extraction,
    )

    profile = resume_extraction_agent.extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_failed",
        application_id="app_failed",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
    )

    assert profile.synthetic_fallback_used is True
    assert profile.full_name.value == "Unknown Candidate"
    assert "Candidate profile extraction failed." in profile.manual_review_flags[1]


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


def test_llm_recovery_disabled_by_default_does_not_call_provider(monkeypatch):
    monkeypatch.delenv("ICSHPS_LLM_EXTRACTION_ENABLED", raising=False)
    metrics = {}

    class FailingProvider:
        def recover(self, *, resume_text, trigger_reasons):
            raise AssertionError("LLM provider should not be called when disabled")

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Kubernetes",
        candidate_id="cand_llm_disabled",
        application_id="app_llm_disabled",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FailingProvider(),
        llm_metrics=metrics,
    )

    assert profile.synthetic_fallback_used is False
    assert metrics["enabled"] is False
    assert metrics["called"] is False
    assert metrics["skipped_reason"] == "llm_recovery_disabled"


def test_llm_recovery_accepts_evidence_backed_skill(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class FakeProvider:
        def recover(self, *, resume_text, trigger_reasons):
            return LLMExtractionRecovery(
                skills=[
                    LLMSkill(
                        name="Kubernetes",
                        normalized_name="kubernetes",
                        category="devops",
                        source_snippet="Kubernetes",
                        confidence=0.7,
                    )
                ]
            )

    profile = extract_candidate_profile(
        "Jane Doe\nExperience\nEngineer at CloudLab, 2020 - 2022\nSkills: Kubernetes",
        candidate_id="cand_llm_skill",
        application_id="app_llm_skill",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FakeProvider(),
        llm_metrics=metrics,
    )

    skill = next(skill for skill in profile.skills if skill.name == "Kubernetes")
    assert skill.evidence[0].extraction_method == "llm_recovery"
    assert skill.evidence[0] in profile.evidence_index
    assert metrics["enabled"] is True
    assert metrics["called"] is True
    assert metrics["accepted_field_count"] == 1
    assert metrics["final_extraction_mode"] == "deterministic_plus_llm"


def test_llm_recovery_not_called_when_deterministic_profile_is_complete(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class FailingProvider:
        def recover(self, *, resume_text, trigger_reasons):
            raise AssertionError("LLM provider should not be called for complete extraction")

    profile = extract_candidate_profile(
        SAMPLE_RESUME_TEXT,
        candidate_id="cand_llm_not_needed",
        application_id="app_llm_not_needed",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FailingProvider(),
        llm_metrics=metrics,
    )

    assert profile.synthetic_fallback_used is False
    assert metrics["enabled"] is True
    assert metrics["called"] is False
    assert metrics["skipped_reason"] == "llm_recovery_not_needed"
    assert metrics["final_extraction_mode"] == "deterministic"


def test_llm_recovery_missing_provider_continues_safely(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    metrics = {}

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Kubernetes",
        candidate_id="cand_llm_no_provider",
        application_id="app_llm_no_provider",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_metrics=metrics,
    )

    assert profile.synthetic_fallback_used is False
    assert profile.full_name.value == "Jane Doe"
    assert metrics["enabled"] is True
    assert metrics["available"] is False
    assert metrics["called"] is False
    assert metrics["skipped_reason"] == "llm_provider_unavailable"


def test_llm_recovery_schema_invalid_provider_output_is_rejected(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class InvalidProvider:
        def recover(self, *, resume_text, trigger_reasons):
            return {"unexpected": "value"}

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Kubernetes",
        candidate_id="cand_llm_invalid_output",
        application_id="app_llm_invalid_output",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=InvalidProvider(),
        llm_metrics=metrics,
    )

    assert profile.synthetic_fallback_used is False
    assert metrics["called"] is True
    assert metrics["validation_error_count"] == 1
    assert metrics["skipped_reason"] == "llm_recovery_failed"
    assert any("failed validation" in flag for flag in profile.manual_review_flags)


def test_llm_recovery_rejects_recommendation_language(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class FakeProvider:
        def recover(self, *, resume_text, trigger_reasons):
            return LLMExtractionRecovery(
                skills=[
                    LLMSkill(
                        name="Good Python",
                        normalized_name="good_python",
                        category="judgment",
                        source_snippet="Good Python",
                        confidence=0.7,
                    )
                ]
            )

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Good Python",
        candidate_id="cand_llm_rejected",
        application_id="app_llm_rejected",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FakeProvider(),
        llm_metrics=metrics,
    )

    assert all(skill.name != "Good Python" for skill in profile.skills)
    assert metrics["recommendation_violation_count"] == 1
    assert metrics["rejected_field_count"] == 1
    assert any("recommendation language" in flag for flag in profile.manual_review_flags)


def test_llm_recovery_rejects_routing_and_pass_fail_language(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class FakeProvider:
        def recover(self, *, resume_text, trigger_reasons):
            return LLMExtractionRecovery(
                skills=[
                    LLMSkill(
                        name="Pass Python routing",
                        normalized_name="pass_python_routing",
                        category="judgment",
                        source_snippet="Pass Python routing",
                        confidence=0.7,
                    )
                ]
            )

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Pass Python routing",
        candidate_id="cand_llm_routing_rejected",
        application_id="app_llm_routing_rejected",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FakeProvider(),
        llm_metrics=metrics,
    )

    assert all(skill.name != "Pass Python routing" for skill in profile.skills)
    assert metrics["recommendation_violation_count"] == 1
    assert metrics["rejected_field_count"] == 1
    assert any("recommendation language" in flag for flag in profile.manual_review_flags)


def test_llm_recovery_rejects_fields_without_resume_evidence(monkeypatch):
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "true")
    metrics = {}

    class FakeProvider:
        def recover(self, *, resume_text, trigger_reasons):
            return LLMExtractionRecovery(
                location=LLMExtractedField(
                    value="Prishtina, Kosovo",
                    source_snippet="Prishtina, Kosovo",
                    confidence=0.7,
                )
            )

    profile = extract_candidate_profile(
        "Jane Doe\nSkills: Kubernetes",
        candidate_id="cand_llm_no_evidence",
        application_id="app_llm_no_evidence",
        role_id="ai_engineer_intern",
        source_file="resume.txt",
        llm_provider=FakeProvider(),
        llm_metrics=metrics,
    )

    assert profile.location is None
    assert metrics["rejected_field_count"] == 1
    assert any("source evidence was not found" in flag for flag in profile.manual_review_flags)


def test_llm_recovery_schema_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        LLMExtractionRecovery.model_validate({"unexpected": "value"})


def test_llm_recovery_max_tokens_env(monkeypatch):
    monkeypatch.delenv("ICSHPS_LLM_EXTRACTION_MAX_TOKENS", raising=False)
    assert llm_recovery_max_tokens() == DEFAULT_LLM_EXTRACTION_MAX_TOKENS

    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_MAX_TOKENS", "800")
    assert llm_recovery_max_tokens() == 800

    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_MAX_TOKENS", "not-a-number")
    assert llm_recovery_max_tokens() == DEFAULT_LLM_EXTRACTION_MAX_TOKENS

    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_MAX_TOKENS", "0")
    assert llm_recovery_max_tokens() == DEFAULT_LLM_EXTRACTION_MAX_TOKENS
