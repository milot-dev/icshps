from __future__ import annotations

from pydantic import Field

from icshps.schemas.common import ICSHPSBaseModel, RoutingCategory
from icshps.schemas.findings import Finding

"""Schemas for final candidate routing and decision artifacts."""

class CandidateRoutingDecision(ICSHPSBaseModel):
    """Final routing recommendation for one candidate application."""

    candidate_id: str
    application_id: str
    routing_category: RoutingCategory
    reason: str
    score: float | None = Field(default=None, ge=0.0, le=100.0)
    blocking_finding_ids: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True


class FinalDecisionArtifact(ICSHPSBaseModel):
    """Final orchestration output containing routing decisions and findings."""
    
    run_id: str
    bundle_id: str
    scenario_type: str
    decisions: list[CandidateRoutingDecision] = Field(default_factory=list)
    findings: list[Finding] = Field(default_factory=list)
    summary: str | None = None