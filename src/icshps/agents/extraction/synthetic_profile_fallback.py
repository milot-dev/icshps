from __future__ import annotations

from pathlib import Path

from icshps.schemas.common import EvidenceRef
from icshps.schemas.profile import CandidateProfile, ExtractedField, ExtractionError


def build_synthetic_candidate_profile(
    *,
    candidate_id: str = "cand_synthetic_unknown",
    application_id: str = "app_synthetic_unknown",
    role_id: str = "unknown_role",
    source_file: str | Path = "unknown_resume.pdf",
    reason: str = "Resume extraction failed or returned incomplete data.",
) -> CandidateProfile:
    fallback_evidence = EvidenceRef(
        evidence_id="ev_synthetic_fallback_001",
        field_path="profile",
        source_path=Path(source_file),
        source_type="synthetic_fallback",
        section="fallback",
        text_snippet=None,
        confidence=0.0,
        extraction_method="synthetic_fallback",
        missing_reason=reason,
        bounding_box=None,
    )

    return CandidateProfile(
        candidate_id=candidate_id,
        application_id=application_id,
        role_id=role_id,
        source_file=str(source_file),
        full_name=ExtractedField(
            value="Unknown Candidate",
            confidence=0.0,
            evidence=[],
        ),
        email=None,
        phone=None,
        location=None,
        skills=[],
        employment_history=[],
        education=[],
        certifications=[],
        total_years_experience_estimate=None,
        relevant_years_experience_estimate=None,
        extraction_confidence=0.0,
        section_confidence={
            "contact": 0.0,
            "skills": 0.0,
            "employment_history": 0.0,
            "education": 0.0,
            "certifications": 0.0,
        },
        evidence_index=[fallback_evidence],
        manual_review_flags=[
            "Synthetic fallback profile used",
            reason,
        ],
        synthetic_fallback_used=True,
        extraction_errors=[
            ExtractionError(
                code="SYNTHETIC_FALLBACK_USED",
                message=reason,
                severity="warning",
                evidence=[fallback_evidence],
            )
        ],
    )


def should_use_synthetic_fallback(
    *,
    extracted_text: str | None = None,
    extraction_failed: bool = False,
    missing_required_fields: bool = False,
) -> bool:
    if extraction_failed:
        return True

    if extracted_text is None or not extracted_text.strip():
        return True

    if missing_required_fields:
        return True

    return False
