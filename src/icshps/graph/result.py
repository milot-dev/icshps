from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from icshps.schemas import FinalDecisionArtifact

WorkflowStatus = Literal["ready_for_downstream", "blocked", "failed"]
EndToEndWorkflowStatus = Literal["completed", "blocked", "failed"]


@dataclass(frozen=True)
class EndToEndWorkflowResult:
    """Controlled result returned by the backend orchestration flow."""

    status: EndToEndWorkflowStatus
    ready_for_downstream: bool
    run_id: str | None
    run_dir: Path | None
    context_packet_path: Path | None
    intake_findings_path: Path | None
    candidate_profile_path: Path | None
    match_scores_path: Path | None
    compliance_flags_path: Path | None
    verification_findings_path: Path | None
    anomaly_findings_path: Path | None
    final_decision: FinalDecisionArtifact | None
    artifact_manifest_path: Path | None
    metrics_path: Path | None
    audit_log_path: Path | None
    created_artifacts: tuple[str, ...]
    pending_artifacts: tuple[str, ...]
    skipped_stages: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    next_step: str

    @property
    def ok(self) -> bool:
        """True when the backend flow completed successfully."""

        return self.status == "completed"
