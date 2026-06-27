from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, TypedDict

from icshps.schemas import FinalDecisionArtifact

WorkflowStatus = Literal["completed", "blocked", "failed"]


class WorkflowState(TypedDict, total=False):
    """State passed between LangGraph orchestration nodes.

    This state is orchestration-only. It carries run metadata, paths,
    stage payloads, warnings, and errors. It must not contain hidden
    business decisions that bypass the normal artifacts.
    """

    bundle_path: Path
    runs_root: Path
    run_id: str | None
    reset: bool

    scaffold: Any
    loaded_bundle: Any
    context: Any
    intake_result: Any
    candidate_profiles: tuple[Any, ...]

    context_packet_path: Path | None
    intake_findings_path: Path | None
    candidate_profile_path: Path | None
    match_scores_path: Path | None
    compliance_flags_path: Path | None
    verification_findings_path: Path | None
    anomaly_findings_path: Path | None
    interview_schedule_path: Path | None
    artifact_manifest_path: Path | None
    metrics_path: Path | None
    audit_log_path: Path | None

    final_decision: FinalDecisionArtifact | None
    status: WorkflowStatus
    ready_for_downstream: bool

    created_artifacts: tuple[str, ...]
    pending_artifacts: tuple[str, ...]
    skipped_stages: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
