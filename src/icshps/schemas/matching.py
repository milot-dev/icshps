from __future__ import annotations

from pydantic import Field

from icshps.schemas.common import EvidenceRef, ICSHPSBaseModel
from icshps.schemas.findings import Finding

"""Schemas for job matching results and requirement checks."""

class RequirementCheck(ICSHPSBaseModel):
    """Result of checking one candidate against one job requirement."""

    requirement_id: str
    label: str
    required: bool = True
    satisfied: bool
    explanation: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CandidateMatchResult(ICSHPSBaseModel):
    """Job fit result for one candidate application."""

    candidate_id: str
    application_id: str
    job_id: str
    score: float = Field(ge=0.0, le=100.0)
    must_have_results: list[RequirementCheck] = Field(default_factory=list)
    nice_to_have_results: list[RequirementCheck] = Field(default_factory=list)
    missing_mandatory_requirements: list[str] = Field(default_factory=list)
    recommendation_signal: str | None = None
    findings: list[Finding] = Field(default_factory=list)


class MatchResultsArtifact(ICSHPSBaseModel):
    """Collection of candidate match results for one pipeline run."""
    
    run_id: str
    results: list[CandidateMatchResult] = Field(default_factory=list)