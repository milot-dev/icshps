from pathlib import Path

import pytest
from pydantic import ValidationError

from icshps.schemas.common import EvidenceRef
from icshps.schemas.profile import (
    CandidateProfile,
    ExtractedField,
    ExtractionError,
    SkillRecord,
)


def test_candidate_profile_valid_minimum():
    profile = CandidateProfile(
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Example Candidate", confidence=0.95),
        extraction_confidence=0.85,
    )

    assert profile.candidate_id == "cand_001"
    assert profile.full_name.value == "Example Candidate"
    assert profile.extraction_confidence == 0.85


def test_invalid_profile_confidence_fails():
    with pytest.raises(ValidationError):
        CandidateProfile(
            candidate_id="cand_001",
            application_id="app_001",
            role_id="ai_engineer_intern",
            source_file="resume.pdf",
            full_name=ExtractedField(
                value="Example Candidate", confidence=0.95),
            extraction_confidence=1.5,
        )


def test_invalid_skill_confidence_fails():
    with pytest.raises(ValidationError):
        SkillRecord(
            name="Python",
            normalized_name="python",
            confidence=1.2,
        )


def test_invalid_extraction_error_code_fails():
    with pytest.raises(ValidationError):
        ExtractionError(
            code="REAL_OCR_FAILED",
            message="Unsupported extraction error code.",
        )


def test_evidence_refs_supported_on_fields_and_profile_index():
    evidence = EvidenceRef(
        evidence_id="ev_contact_full_name_001",
        field_path="full_name",
        source_path=Path("resumes/cand_001_resume.pdf"),
        source_type="resume_pdf",
        page_number=1,
        section="contact",
        text_snippet="Example Candidate",
        confidence=0.9,
        extraction_method="regex_resume_text",
        bounding_box={
            "x0": 72.0,
            "y0": 88.5,
            "x1": 196.4,
            "y1": 101.2,
            "unit": "points",
        },
    )

    profile = CandidateProfile(
        candidate_id="cand_001",
        application_id="app_001",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        full_name=ExtractedField(
            value="Example Candidate",
            confidence=0.95,
            evidence=[evidence],
        ),
        extraction_confidence=0.85,
        evidence_index=[evidence],
    )

    assert profile.full_name.evidence[0].source_type == "resume_pdf"
    assert profile.evidence_index[0].section == "contact"
    assert profile.evidence_index[0].evidence_id == "ev_contact_full_name_001"
    assert profile.evidence_index[0].field_path == "full_name"
    assert profile.evidence_index[0].bounding_box is not None


def test_synthetic_fallback_profile_passes():
    profile = CandidateProfile(
        candidate_id="cand_fallback_001",
        application_id="app_fallback_001",
        role_id="ai_engineer_intern",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Fallback Candidate", confidence=0.5),
        extraction_confidence=0.5,
        synthetic_fallback_used=True,
        manual_review_flags=["Synthetic fallback profile used"],
        extraction_errors=[
            ExtractionError(
                code="SYNTHETIC_FALLBACK_USED",
                message="Resume extraction was incomplete, fallback profile was used.",
                severity="warning",
            )
        ],
    )

    assert profile.synthetic_fallback_used is True
    assert profile.manual_review_flags
    assert profile.extraction_errors[0].code == "SYNTHETIC_FALLBACK_USED"


def test_missing_required_candidate_id_fails():
    with pytest.raises(ValidationError):
        CandidateProfile(
            application_id="app_001",
            role_id="ai_engineer_intern",
            source_file="resume.pdf",
            full_name=ExtractedField(
                value="Example Candidate", confidence=0.95),
            extraction_confidence=0.85,
        )


def test_missing_required_role_id_fails():
    with pytest.raises(ValidationError):
        CandidateProfile(
            candidate_id="cand_001",
            application_id="app_001",
            source_file="resume.pdf",
            full_name=ExtractedField(value="Example Candidate", confidence=0.95),
            extraction_confidence=0.85,
        )


def test_candidate_profile_example_json_is_valid():
    example_path = Path("data/sample_outputs/candidate_profile.example.json")

    profile = CandidateProfile.model_validate_json(example_path.read_text())

    assert profile.candidate_id == "cand_001"
    assert profile.role_id == "ai_engineer_intern"
