from __future__ import annotations

from typing import Literal
from pydantic import Field

from icshps.schemas.common import EvidenceRef, ICSHPSBaseModel

"""Schemas for extracted candidate profile artifacts."""


class ExtractedField(ICSHPSBaseModel):
    """Single extracted candidate field with confidence and evidence."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class SkillRecord(ICSHPSBaseModel):
    """Normalized skill extracted from a resume."""

    name: str
    normalized_name: str
    category: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class EmploymentRecord(ICSHPSBaseModel):
    """Structured employment history entry extracted from a resume."""

    company: str
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    is_current: bool = False
    responsibilities: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class EducationRecord(ICSHPSBaseModel):
    """Structured education entry extracted from a resume."""

    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    country: str | None = None
    start_year: int | None = None
    end_year: int | None = None
    is_international: bool = False
    verification_status: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CertificationRecord(ICSHPSBaseModel):
    """Structured certification entry extracted from resume or credential evidence."""

    name: str
    issuer: str | None = None
    issued_date: str | None = None
    expiration_date: str | None = None
    credential_id: str | None = None
    verification_status: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class ExtractionError(ICSHPSBaseModel):
    """Controlled extraction issue produced during resume parsing."""

    code: Literal[
        "PDF_TEXT_EMPTY",
        "LOW_CONFIDENCE_FIELD",
        "MISSING_CONTACT_INFO",
        "MISSING_EMPLOYMENT_HISTORY",
        "MISSING_EDUCATION",
        "SYNTHETIC_FALLBACK_USED",
        "UNSUPPORTED_RESUME_FORMAT",
    ]
    message: str
    field_name: str | None = None
    severity: Literal["info", "warning", "error"] = "warning"
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CandidateProfile(ICSHPSBaseModel):
    """Normalized candidate profile produced by the resume extraction agent."""

    candidate_id: str
    application_id: str
    role_id: str
    source_file: str

    full_name: ExtractedField
    email: ExtractedField | None = None
    phone: ExtractedField | None = None
    location: ExtractedField | None = None

    skills: list[SkillRecord] = Field(default_factory=list)
    employment_history: list[EmploymentRecord] = Field(default_factory=list)
    education: list[EducationRecord] = Field(default_factory=list)
    certifications: list[CertificationRecord] = Field(default_factory=list)

    total_years_experience_estimate: float | None = Field(default=None, ge=0.0)
    relevant_years_experience_estimate: float | None = Field(
        default=None, ge=0.0)

    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    section_confidence: dict[str, float] = Field(default_factory=dict)

    evidence_index: list[EvidenceRef] = Field(default_factory=list)
    manual_review_flags: list[str] = Field(default_factory=list)
    synthetic_fallback_used: bool = False
    extraction_errors: list[ExtractionError] = Field(default_factory=list)
