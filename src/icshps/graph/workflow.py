from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from icshps.agents.intake import ApplicationIntakeResult, run_application_intake
from icshps.schemas.run import ArtifactStatus, RunArtifactManifest, RunMetadata, RunStatus
from icshps.services.bundle_loader import LoadedBundle, load_hiring_bundle
from icshps.services.run_scaffolding import RunScaffold, prepare_run_scaffold

WorkflowStatus = Literal["ready_for_downstream", "blocked", "failed"]


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
class _WorkflowArtifacts:
    created: tuple[str, ...]
    pending: tuple[str, ...]


def run_initial_workflow(
    bundle_path: str | Path,
    *,
    runs_root: str | Path = Path("runs"),
    run_id: str | None = None,
    reset: bool = True,
) -> InitialWorkflowResult:
    """
    Run the completed Sprint 1 foundations in deterministic order.

    Order:
        1. prepare run scaffold
        2. load and validate Hiring Bundle
        3. run Application Intake & Context Agent

    This function intentionally stops after intake. It does not create fake
    extraction, matching, compliance, verification, shortlist, or hiring packet
    outputs. Those artifacts remain reserved for Member 2 and Member 3 work.
    """

    scaffold: RunScaffold | None = None

    try:
        scaffold = prepare_run_scaffold(
            bundle_path=Path(bundle_path),
            runs_root=Path(runs_root),
            run_id=run_id,
            reset=reset,
        )

        loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)
        intake_result = run_application_intake(
            loaded_bundle=loaded_bundle,
            scaffold=scaffold,
        )

        status: WorkflowStatus = (
            "ready_for_downstream" if intake_result.ready_for_downstream else "blocked"
        )
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
    data = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")
