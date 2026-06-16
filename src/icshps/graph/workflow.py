from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from icshps.agents.anomaly import run_anomaly_stage
from icshps.agents.compliance import run_compliance_stage
from icshps.agents.extraction import run_resume_extraction_stage
from icshps.agents.intake import ApplicationIntakeResult, run_application_intake
from icshps.agents.matching import run_matching_stage
from icshps.agents.orchestrator import build_final_decision_from_run
from icshps.agents.verification import run_verification_stage
from icshps.schemas import (
    ArtifactStatus,
    FinalDecisionArtifact,
    RunArtifactManifest,
    RunMetadata,
    RunStatus,
)
from icshps.services import (
    RunScaffold,
    LoadedBundle,
    load_hiring_bundle,
    prepare_run_scaffold,
    write_final_run_artifacts
)

WorkflowStatus = Literal["ready_for_downstream", "blocked", "failed"]
EndToEndWorkflowStatus = Literal["completed", "blocked", "failed"]


# note: InitialWorkflow will be deprecated after sprint 2
@dataclass(frozen=True)
class InitialWorkflowResult:
    """Controlled result returned by the Sprint 1 initial workflow skeleton."""

    status: WorkflowStatus
    ready_for_downstream: bool
    run_id: str | None
    run_dir: Path | None
    context_packet_path: Path | None
    intake_findings_path: Path | None
    artifact_manifest_path: Path | None
    metrics_path: Path | None
    audit_log_path: Path | None
    created_artifacts: tuple[str, ...]
    pending_artifacts: tuple[str, ...]
    warnings: tuple[str, ...]
    errors: tuple[str, ...]
    next_step: str

    @property
    def ok(self) -> bool:
        """True only when the Sprint 1 skeleton finished and downstream agents may run."""

        return self.status == "ready_for_downstream" and self.ready_for_downstream


@dataclass(frozen=True)
class EndToEndWorkflowResult:
    """Controlled result returned by the Sprint 2 backend orchestration flow."""

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
        """True when the backend flow reached its current Sprint 2 stop point."""

        return self.status == "completed"


@dataclass(frozen=True)
class _WorkflowArtifacts:
    created: tuple[str, ...]
    pending: tuple[str, ...]


@dataclass(frozen=True)
class _WorkflowFoundation:
    scaffold: RunScaffold
    loaded_bundle: LoadedBundle
    intake_result: ApplicationIntakeResult
    status: WorkflowStatus


# note: this will be deprecated after Sprint 2, but keep it stable for debugging.
def run_initial_workflow(
    bundle_path: str | Path,
    *,
    runs_root: str | Path = Path("runs"),
    run_id: str | None = None,
    reset: bool = True,
) -> InitialWorkflowResult:
    """
    Run the completed Sprint 1 foundations in deterministic order.

    This workflow intentionally stops after intake. It reuses the same foundation
    helper as the Sprint 2 end-to-end flow so scaffold/load/intake behavior stays
    consistent and does not duplicate logic.
    """

    scaffold: RunScaffold | None = None

    try:
        foundation = _run_workflow_foundation(
            bundle_path=bundle_path,
            runs_root=runs_root,
            run_id=run_id,
            reset=reset,
        )

        scaffold = foundation.scaffold
        loaded_bundle = foundation.loaded_bundle
        intake_result = foundation.intake_result
        status = foundation.status

        artifacts = _read_workflow_artifacts(scaffold.artifact_manifest_path)

        _append_workflow_audit_event(
            scaffold=scaffold,
            status=status,
            intake_result=intake_result,
            loaded_bundle=loaded_bundle,
            pending_artifacts=artifacts.pending,
        )
        _append_workflow_audit_log_section(
            scaffold=scaffold,
            status=status,
            intake_result=intake_result,
            pending_artifacts=artifacts.pending,
        )
        _set_run_metadata_status(scaffold, RunStatus.COMPLETED)

        return InitialWorkflowResult(
            status=status,
            ready_for_downstream=intake_result.ready_for_downstream,
            run_id=scaffold.run_id,
            run_dir=scaffold.run_dir,
            context_packet_path=intake_result.context_packet_path,
            intake_findings_path=intake_result.intake_findings_path,
            artifact_manifest_path=scaffold.artifact_manifest_path,
            metrics_path=scaffold.artifacts_dir / "metrics.json",
            audit_log_path=scaffold.artifacts_dir / "audit_log.md",
            created_artifacts=artifacts.created,
            pending_artifacts=artifacts.pending,
            warnings=intake_result.warnings,
            errors=intake_result.errors,
            next_step=_next_step_for(status),
        )

    except Exception as exc:  # pragma: no cover - exercised through behavior tests.
        if scaffold is not None:
            _append_failure_audit_event(scaffold=scaffold, error=str(exc))
            _append_failure_audit_log_section(scaffold=scaffold, error=str(exc))
            _set_run_metadata_status(scaffold, RunStatus.FAILED)
            artifacts = _read_workflow_artifacts(scaffold.artifact_manifest_path)

            return InitialWorkflowResult(
                status="failed",
                ready_for_downstream=False,
                run_id=scaffold.run_id,
                run_dir=scaffold.run_dir,
                context_packet_path=None,
                intake_findings_path=None,
                artifact_manifest_path=scaffold.artifact_manifest_path,
                metrics_path=scaffold.artifacts_dir / "metrics.json",
                audit_log_path=scaffold.artifacts_dir / "audit_log.md",
                created_artifacts=artifacts.created,
                pending_artifacts=artifacts.pending,
                warnings=(),
                errors=(str(exc),),
                next_step="Fix the unexpected workflow error before rerunning.",
            )

        return InitialWorkflowResult(
            status="failed",
            ready_for_downstream=False,
            run_id=None,
            run_dir=None,
            context_packet_path=None,
            intake_findings_path=None,
            artifact_manifest_path=None,
            metrics_path=None,
            audit_log_path=None,
            created_artifacts=(),
            pending_artifacts=(),
            warnings=(),
            errors=(str(exc),),
            next_step="Provide an existing Hiring Bundle path before rerunning.",
        )


def run_end_to_end_workflow(
    bundle_path: str | Path,
    *,
    runs_root: str | Path = Path("runs"),
    run_id: str | None = None,
    reset: bool = True,
) -> EndToEndWorkflowResult:
    """
    Run the current Sprint 2 backend pipeline in deterministic order.

    This flow integrates available stage outputs and builds in-memory Task 4
    routing decisions. It intentionally stops before writing final_decision,
    shortlist, hiring packet, metrics finalization, and polished audit artifacts.
    """

    scaffold: RunScaffold | None = None
    warnings: list[str] = []
    skipped_stages: list[str] = []

    candidate_profile_path: Path | None = None
    match_scores_path: Path | None = None
    compliance_flags_path: Path | None = None
    verification_findings_path: Path | None = None
    anomaly_findings_path: Path | None = None
    final_decision: FinalDecisionArtifact | None = None

    try:
        foundation = _run_workflow_foundation(
            bundle_path=bundle_path,
            runs_root=runs_root,
            run_id=run_id,
            reset=reset,
        )

        scaffold = foundation.scaffold
        loaded_bundle = foundation.loaded_bundle
        intake_result = foundation.intake_result
        warnings.extend(intake_result.warnings)

        if not intake_result.ready_for_downstream or loaded_bundle.context is None:
            status: EndToEndWorkflowStatus = "blocked"
            skipped_stages.extend(
                [
                    "candidate_profile",
                    "match_scores",
                    "compliance_flags",
                    "verification_findings",
                    "anomaly_findings",
                ]
            )
        else:
            context = loaded_bundle.context

            profile_stage = run_resume_extraction_stage(
                scaffold=scaffold,
                context=context,
            )
            candidate_profile_path = profile_stage.path
            skipped_stages.extend(profile_stage.skipped_stages)
            warnings.extend(profile_stage.warnings)

            match_stage = run_matching_stage(
                scaffold=scaffold,
                context=context,
            )
            match_scores_path = match_stage.path
            skipped_stages.extend(match_stage.skipped_stages)
            warnings.extend(match_stage.warnings)

            verification_stage = run_verification_stage(
                scaffold=scaffold,
                context=context,
            )
            verification_findings_path = verification_stage.path
            skipped_stages.extend(verification_stage.skipped_stages)
            warnings.extend(verification_stage.warnings)

            compliance_stage = run_compliance_stage(
                scaffold=scaffold,
                context=context,
            )
            compliance_flags_path = compliance_stage.path
            skipped_stages.extend(compliance_stage.skipped_stages)
            warnings.extend(compliance_stage.warnings)

            anomaly_stage = run_anomaly_stage(scaffold=scaffold, context=context)
            anomaly_findings_path = anomaly_stage.path
            skipped_stages.extend(anomaly_stage.skipped_stages)
            warnings.extend(anomaly_stage.warnings)

            final_decision = build_final_decision_from_run(scaffold)

            write_final_run_artifacts(
                scaffold=scaffold,
                final_decision=final_decision,
            )

            status = "completed"

        artifacts = _read_workflow_artifacts(scaffold.artifact_manifest_path)
        skipped = tuple(sorted(set(skipped_stages)))
        deduped_warnings = tuple(dict.fromkeys(warnings))

        _update_end_to_end_metrics(
            scaffold=scaffold,
            loaded_bundle=loaded_bundle,
            status=status,
            created_artifacts=artifacts.created,
            skipped_stages=skipped,
        )
        _append_end_to_end_audit_event(
            scaffold=scaffold,
            status=status,
            intake_result=intake_result,
            created_artifacts=artifacts.created,
            pending_artifacts=artifacts.pending,
            skipped_stages=skipped,
        )
        _append_end_to_end_audit_log_section(
            scaffold=scaffold,
            status=status,
            created_artifacts=artifacts.created,
            pending_artifacts=artifacts.pending,
            skipped_stages=skipped,
        )
        _set_run_metadata_status(scaffold, RunStatus.COMPLETED)

        return EndToEndWorkflowResult(
            status=status,
            ready_for_downstream=intake_result.ready_for_downstream,
            run_id=scaffold.run_id,
            run_dir=scaffold.run_dir,
            context_packet_path=intake_result.context_packet_path,
            intake_findings_path=intake_result.intake_findings_path,
            candidate_profile_path=candidate_profile_path,
            match_scores_path=match_scores_path,
            compliance_flags_path=compliance_flags_path,
            verification_findings_path=verification_findings_path,
            anomaly_findings_path=anomaly_findings_path,
            final_decision=final_decision,
            artifact_manifest_path=scaffold.artifact_manifest_path,
            metrics_path=scaffold.artifacts_dir / "metrics.json",
            audit_log_path=scaffold.artifacts_dir / "audit_log.md",
            created_artifacts=artifacts.created,
            pending_artifacts=artifacts.pending,
            skipped_stages=skipped,
            warnings=deduped_warnings,
            errors=intake_result.errors,
            next_step=_end_to_end_next_step_for(status),
        )

    except Exception as exc:
        if scaffold is not None:
            _append_failure_audit_event(scaffold=scaffold, error=str(exc))
            _append_failure_audit_log_section(scaffold=scaffold, error=str(exc))
            _set_run_metadata_status(scaffold, RunStatus.FAILED)
            artifacts = _read_workflow_artifacts(scaffold.artifact_manifest_path)

            return EndToEndWorkflowResult(
                status="failed",
                ready_for_downstream=False,
                run_id=scaffold.run_id,
                run_dir=scaffold.run_dir,
                context_packet_path=None,
                intake_findings_path=None,
                candidate_profile_path=candidate_profile_path,
                match_scores_path=match_scores_path,
                compliance_flags_path=compliance_flags_path,
                verification_findings_path=verification_findings_path,
                anomaly_findings_path=anomaly_findings_path,
                final_decision=final_decision,
                artifact_manifest_path=scaffold.artifact_manifest_path,
                metrics_path=scaffold.artifacts_dir / "metrics.json",
                audit_log_path=scaffold.artifacts_dir / "audit_log.md",
                created_artifacts=artifacts.created,
                pending_artifacts=artifacts.pending,
                skipped_stages=tuple(sorted(set(skipped_stages))),
                warnings=tuple(dict.fromkeys(warnings)),
                errors=(str(exc),),
                next_step=_end_to_end_next_step_for("failed"),
            )

        return EndToEndWorkflowResult(
            status="failed",
            ready_for_downstream=False,
            run_id=None,
            run_dir=None,
            context_packet_path=None,
            intake_findings_path=None,
            candidate_profile_path=None,
            match_scores_path=None,
            compliance_flags_path=None,
            verification_findings_path=None,
            anomaly_findings_path=None,
            final_decision=None,
            artifact_manifest_path=None,
            metrics_path=None,
            audit_log_path=None,
            created_artifacts=(),
            pending_artifacts=(),
            skipped_stages=(),
            warnings=(),
            errors=(str(exc),),
            next_step=_end_to_end_next_step_for("failed"),
        )


def _run_workflow_foundation(
    *,
    bundle_path: str | Path,
    runs_root: str | Path,
    run_id: str | None,
    reset: bool,
) -> _WorkflowFoundation:
    """Run the shared scaffold, bundle loading, and intake foundation."""

    scaffold = prepare_run_scaffold(
        bundle_path=Path(bundle_path),
        runs_root=Path(runs_root),
        run_id=run_id,
        reset=reset,
    )
    _set_run_metadata_status(scaffold, RunStatus.RUNNING)

    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)
    intake_result = run_application_intake(
        loaded_bundle=loaded_bundle,
        scaffold=scaffold,
    )

    status: WorkflowStatus = (
        "ready_for_downstream" if intake_result.ready_for_downstream else "blocked"
    )

    return _WorkflowFoundation(
        scaffold=scaffold,
        loaded_bundle=loaded_bundle,
        intake_result=intake_result,
        status=status,
    )


def _end_to_end_next_step_for(status: EndToEndWorkflowStatus) -> str:
    if status == "completed":
        return "Final run artifacts are written; Task 6 can add the one-command CLI when explicitly started."

    if status == "blocked":
        return "Fix intake findings before running downstream orchestration."

    return "Fix the workflow failure before rerunning."


def _update_end_to_end_metrics(
    *,
    scaffold: RunScaffold,
    loaded_bundle: LoadedBundle,
    status: EndToEndWorkflowStatus,
    created_artifacts: tuple[str, ...],
    skipped_stages: tuple[str, ...],
) -> None:
    metrics_path = scaffold.artifacts_dir / "metrics.json"
    payload = _read_json_object(metrics_path)
    context = loaded_bundle.context

    payload.update(
        {
            "status": status,
            "candidate_count": len(context.candidates) if context else 0,
            "artifacts_created": list(created_artifacts),
            "skipped_stages": list(skipped_stages),
            "end_to_end_orchestration_completed": status == "completed",
        }
    )

    _write_json(metrics_path, payload)


def _append_end_to_end_audit_event(
    *,
    scaffold: RunScaffold,
    status: EndToEndWorkflowStatus,
    intake_result: ApplicationIntakeResult,
    created_artifacts: tuple[str, ...],
    pending_artifacts: tuple[str, ...],
    skipped_stages: tuple[str, ...],
) -> None:
    _append_jsonl(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "end_to_end_workflow_completed",
            "run_id": scaffold.run_id,
            "status": status,
            "ready_for_downstream": intake_result.ready_for_downstream,
            "created_artifacts": list(created_artifacts),
            "pending_artifacts": list(pending_artifacts),
            "skipped_stages": list(skipped_stages),
        },
    )


def _append_end_to_end_audit_log_section(
    *,
    scaffold: RunScaffold,
    status: EndToEndWorkflowStatus,
    created_artifacts: tuple[str, ...],
    pending_artifacts: tuple[str, ...],
    skipped_stages: tuple[str, ...],
) -> None:
    created_lines = "".join(f"- `{artifact}`\n" for artifact in created_artifacts)
    pending_lines = "".join(f"- `{artifact}`\n" for artifact in pending_artifacts)
    skipped_lines = "".join(f"- `{stage}`\n" for stage in skipped_stages)

    if not created_lines:
        created_lines = "- None.\n"

    if not pending_lines:
        pending_lines = "- None.\n"

    if not skipped_lines:
        skipped_lines = "- None.\n"

    section = (
        "\n## Sprint 2 Task 3: End-to-End Orchestration Flow\n\n"
        "Executed deterministic backend order:\n\n"
        "1. `prepare_run_scaffold`\n"
        "2. `load_hiring_bundle`\n"
        "3. `run_application_intake`\n"
        "4. available resume extraction and candidate profile stage\n"
        "5. available JD matching stage\n"
        "6. available verification and compliance stages\n"
        "7. available anomaly stage\n\n"
        f"- Workflow status: `{status}`\n"
        "- Final artifact generation: `completed`\n"
        "- Stop boundary: one-command CLI, scenario validation loop, and README/demo instructions are postponed.\n"
        f"- Next step: {_end_to_end_next_step_for(status)}\n\n"
        "### Created artifacts\n\n"
        f"{created_lines}\n"
        "### Pending artifacts\n\n"
        f"{pending_lines}\n"
        "### Skipped stages\n\n"
        f"{skipped_lines}"
    )

    with (scaffold.artifacts_dir / "audit_log.md").open("a", encoding="utf-8") as file:
        file.write(section)


def _next_step_for(status: WorkflowStatus) -> str:
    if status == "ready_for_downstream":
        return "Pass inputs/context_packet.json to the Resume Extraction Agent."

    if status == "blocked":
        return "Fix intake findings before running downstream agents."

    return "Fix the workflow failure before rerunning."


def _read_workflow_artifacts(path: Path) -> _WorkflowArtifacts:
    payload = _read_json_object(path)
    manifest = RunArtifactManifest.model_validate(payload)

    created: list[str] = []
    pending: list[str] = []

    for key, artifact in sorted(manifest.artifacts.items()):
        if artifact.status == ArtifactStatus.CREATED:
            created.append(key)
        else:
            pending.append(key)

    return _WorkflowArtifacts(created=tuple(created), pending=tuple(pending))


def _append_workflow_audit_event(
    *,
    scaffold: RunScaffold,
    status: WorkflowStatus,
    intake_result: ApplicationIntakeResult,
    loaded_bundle: LoadedBundle,
    pending_artifacts: tuple[str, ...],
) -> None:
    context = loaded_bundle.context

    _append_jsonl(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "initial_workflow_completed",
            "run_id": scaffold.run_id,
            "status": status,
            "ready_for_downstream": intake_result.ready_for_downstream,
            "bundle_id": context.bundle.id if context else None,
            "scenario_type": context.scenario.type if context else None,
            "blocking_finding_count": intake_result.blocking_finding_count,
            "finding_count": intake_result.finding_count,
            "pending_artifacts": list(pending_artifacts),
        },
    )


def _append_workflow_audit_log_section(
    *,
    scaffold: RunScaffold,
    status: WorkflowStatus,
    intake_result: ApplicationIntakeResult,
    pending_artifacts: tuple[str, ...],
) -> None:
    pending_lines = "".join(f"- `{artifact}`\n" for artifact in pending_artifacts)
    if not pending_lines:
        pending_lines = "- None.\n"

    section = (
        "\n## Task 7: Initial Workflow Skeleton\n\n"
        "Executed deterministic Sprint 1 workflow order:\n\n"
        "1. `prepare_run_scaffold`\n"
        "2. `load_hiring_bundle`\n"
        "3. `run_application_intake`\n\n"
        f"- Workflow status: `{status}`\n"
        f"- Ready for downstream: `{intake_result.ready_for_downstream}`\n"
        f"- Blocking intake findings: `{intake_result.blocking_finding_count}`\n"
        f"- Next step: {_next_step_for(status)}\n\n"
        "### Reserved downstream artifacts\n\n"
        f"{pending_lines}"
    )

    with (scaffold.artifacts_dir / "audit_log.md").open("a", encoding="utf-8") as file:
        file.write(section)


def _append_failure_audit_event(*, scaffold: RunScaffold, error: str) -> None:
    _append_jsonl(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "initial_workflow_failed",
            "run_id": scaffold.run_id,
            "status": "failed",
            "error": error,
        },
    )


def _append_failure_audit_log_section(*, scaffold: RunScaffold, error: str) -> None:
    section = (
        "\n## Task 7: Initial Workflow Skeleton\n\n"
        "- Workflow status: `failed`\n"
        f"- Error: {error}\n"
        "- Next step: Fix the workflow failure before rerunning.\n"
    )

    with (scaffold.artifacts_dir / "audit_log.md").open("a", encoding="utf-8") as file:
        file.write(section)


def _set_run_metadata_status(scaffold: RunScaffold, status: RunStatus) -> None:
    payload = _read_json_object(scaffold.metadata_path)
    metadata = RunMetadata.model_validate(payload)
    updated = metadata.model_copy(update={"status": status})
    _write_json(scaffold.metadata_path, updated)


def _append_jsonl(path: Path, event: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as file:
        file.write(json.dumps(event, sort_keys=True) + "\n")


def _read_json_object(path: Path) -> dict[str, object]:
    raw = json.loads(path.read_text(encoding="utf-8"))

    if not isinstance(raw, dict):
        raise ValueError(f"Expected JSON object at {path}")

    return raw


def _write_json(path: Path, payload: BaseModel | dict[str, object]) -> None:
    data = (
        payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    )
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
