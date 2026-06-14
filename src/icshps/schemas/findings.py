from __future__ import annotations

from pydantic import Field

from icshps.schemas.common import EvidenceRef, FindingCategory, ICSHPSBaseModel, Severity

"""Schemas for unified agent findings and finding artifacts."""

class Finding(ICSHPSBaseModel):
    """Single traceable issue, signal, or recommendation produced by an agent."""

    id: str
    created_at: str = "1970-01-01T00:00:00Z"
    source_agent: str
    category: FindingCategory
    severity: Severity
    title: str
    description: str
    reason: str | None = None
    candidate_id: str | None = None
    application_id: str | None = None
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    recommendation: str | None = None
    requires_human_review: bool = True


class FindingsArtifact(ICSHPSBaseModel):
    """Collection of findings produced during one pipeline run."""
    
    run_id: str
    findings: list[Finding] = Field(default_factory=list)
