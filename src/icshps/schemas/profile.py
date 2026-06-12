from __future__ import annotations

from pydantic import Field

from icshps.schemas.common import EvidenceRef, ICSHPSBaseModel

"""Schemas for extracted candidate profile artifacts."""

class ExtractedField(ICSHPSBaseModel):
    """Single extracted candidate field with confidence and evidence."""

    value: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class EmploymentRecord(ICSHPSBaseModel):
    """Structured employment history entry extracted from a resume."""

    company: str
    title: str | None = None
    start_date: str | None = None
    end_date: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class EducationRecord(ICSHPSBaseModel):
    """Structured education entry extracted from a resume or mock evidence."""
    
    institution: str
    degree: str | None = None
    field_of_study: str | None = None
    country: str | None = None
    verification_status: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CertificationRecord(ICSHPSBaseModel):
    """Structured certification entry extracted from resume or credential evidence."""

    name: str
    issuer: str | None = None
    issued_date: str | None = None
    expiration_date: str | None = None
    verification_status: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CandidateProfile(ICSHPSBaseModel):
    """Normalized candidate profile produced by the resume extraction agent."""
    
    candidate_id: str
    application_id: str
    full_name: ExtractedField
    email: ExtractedField | None = None
    phone: ExtractedField | None = None
    skills: list[str] = Field(default_factory=list)
    employment_history: list[EmploymentRecord] = Field(default_factory=list)
    education: list[EducationRecord] = Field(default_factory=list)
    certifications: list[CertificationRecord] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    manual_review_flags: list[str] = Field(default_factory=list)