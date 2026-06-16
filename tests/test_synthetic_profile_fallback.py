from icshps.agents.extraction import (
    build_synthetic_candidate_profile,
    should_use_synthetic_fallback,
)
from icshps.schemas.profile import CandidateProfile


def test_empty_text_requires_synthetic_fallback():
    assert should_use_synthetic_fallback(extracted_text="") is True
    assert should_use_synthetic_fallback(extracted_text="   ") is True


def test_extraction_failure_requires_synthetic_fallback():
    assert should_use_synthetic_fallback(
        extracted_text=None,
        extraction_failed=True,
    ) is True


def test_missing_required_fields_requires_synthetic_fallback():
    assert should_use_synthetic_fallback(
        extracted_text="Jane Doe\nPython\nAI Engineer",
        missing_required_fields=True,
    ) is True


def test_valid_text_does_not_require_fallback():
    assert should_use_synthetic_fallback(
        extracted_text="Jane Doe\nPython\nAI Engineer",
    ) is False


def test_synthetic_profile_validates_against_schema():
    profile = build_synthetic_candidate_profile(
        candidate_id="cand_test",
        application_id="app_test",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        reason="PDF extraction returned empty text.",
    )

    assert isinstance(profile, CandidateProfile)
    assert profile.synthetic_fallback_used is True
    assert profile.full_name.value == "Unknown Candidate"
    assert profile.extraction_confidence == 0.0
    assert profile.extraction_errors[0].code == "SYNTHETIC_FALLBACK_USED"


def test_synthetic_profile_includes_fallback_reason():
    reason = "PDF extraction returned empty text."

    profile = build_synthetic_candidate_profile(
        candidate_id="cand_test",
        application_id="app_test",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        reason=reason,
    )

    assert reason in profile.manual_review_flags
    assert profile.extraction_errors[0].message == reason


def test_synthetic_profile_is_deterministic():
    profile_1 = build_synthetic_candidate_profile(
        candidate_id="cand_test",
        application_id="app_test",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        reason="PDF extraction failed.",
    )

    profile_2 = build_synthetic_candidate_profile(
        candidate_id="cand_test",
        application_id="app_test",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        reason="PDF extraction failed.",
    )

    assert profile_1.model_dump() == profile_2.model_dump()
