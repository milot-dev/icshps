from __future__ import annotations

from typing import Any

from pydantic import Field

from icshps.schemas.common import ICSHPSBaseModel


class AtsPayloadRecord(ICSHPSBaseModel):
    """One local-only ATS-ready record derived from a routing decision."""

    candidate_id: str
    application_id: str
    requisition_id: str | None = None
    routing_category: str
    status: str
    score: float | None = None
    reason: str
    blocking_finding_ids: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True


class AtsPayload(ICSHPSBaseModel):
    """Dry-run ATS payload artifact. It never calls a real external ATS."""

    run_id: str
    bundle_id: str
    scenario_type: str
    target_system: str = "local_demo_ats"
    dry_run: bool = True
    export_enabled: bool = True
    requisition: dict[str, Any] = Field(default_factory=dict)
    records: list[AtsPayloadRecord] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
