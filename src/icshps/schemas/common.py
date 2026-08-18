from __future__ import annotations

from enum import Enum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

"""Shared schema primitives used across the ICSHPS pipeline."""

class ICSHPSBaseModel(BaseModel):
    """Base model for all shared ICSHPS schemas."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
    )


class Severity(str, Enum):
    """Allowed severity levels for validation issues and agent findings."""
    
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    BLOCKING = "blocking"


class FindingCategory(str, Enum):
    """Standard categories used to group findings across agents."""

    INTAKE = "intake"
    EXTRACTION = "extraction"
    MATCHING = "matching"
    COMPLIANCE = "compliance"
    CREDENTIAL = "credential"
    LINKEDIN_CONSISTENCY = "linkedin_consistency"
    ANOMALY = "anomaly"
    FRAUD = "fraud"
    TRIAGE = "triage"


class RoutingCategory(str, Enum):
    """Supported human-review routing outcomes for candidates."""

    ADVANCE_TO_INTERVIEW_REVIEW = "Advance to interview review"
    FAST_TRACK_REVIEW = "Fast-track review"
    RECOMMENDED_REJECTION_HUMAN_APPROVAL = "Recommended rejection — human approval required"
    MANUAL_REVIEW = "Manual review"
    CREDENTIAL_VERIFICATION_PENDING = "Credential verification pending"
    EMPLOYMENT_HISTORY_INCONSISTENCY = "Employment history inconsistency"
    EEO_COMPLIANCE_REVIEW = "EEO compliance review"
    DUPLICATE_MULTI_ROLE_REVIEW = "Duplicate / multi-role review"
    SURGE_PROCESSING_MODE = "Surge processing mode"


class BoundingBox(ICSHPSBaseModel):
    """PDF text bounding box in page coordinate space."""

    x0: float
    y0: float
    x1: float
    y1: float
    unit: str = "points"


class EvidenceRef(ICSHPSBaseModel):
    """Reference to source evidence used to support an extraction, finding, or decision."""

    evidence_id: str | None = None
    field_path: str | None = None
    source_path: Path
    source_type: str = Field(description="Example: resume_pdf, job_description, skills_matrix, policy, mock_data")
    page_number: int | None = None
    section: str | None = None
    text_snippet: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    extraction_method: str | None = None
    missing_reason: str | None = None
    bounding_box: BoundingBox | None = None
