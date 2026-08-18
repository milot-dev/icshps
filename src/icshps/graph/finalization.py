from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from icshps.agents.intake import ApplicationIntakeResult
from icshps.graph.result import EndToEndWorkflowStatus
from icshps.schemas import ArtifactStatus, RunArtifactManifest, RunMetadata, RunStatus
from icshps.services import LoadedBundle, RunScaffold
from icshps.utils.file_io import append_jsonl, read_json_object, write_json


@dataclass(frozen=True)
class WorkflowArtifacts:
    created: tuple[str, ...]
    pending: tuple[str, ...]


def end_to_end_next_step_for(status: EndToEndWorkflowStatus) -> str:
    if status == "completed":
        return "Final run artifacts are written and ready for local review."

    if status == "blocked":
        return "Fix intake findings before running downstream orchestration."

    return "Fix the workflow failure before rerunning."


def update_end_to_end_metrics(
    *,
    scaffold: RunScaffold,
    loaded_bundle: LoadedBundle,
    status: EndToEndWorkflowStatus,
    created_artifacts: tuple[str, ...],
    skipped_stages: tuple[str, ...],
) -> None:
    metrics_path = scaffold.artifacts_dir / "metrics.json"
    payload = read_json_object(metrics_path)
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

    write_json(metrics_path, payload)


def append_end_to_end_audit_event(
    *,
    scaffold: RunScaffold,
    status: EndToEndWorkflowStatus,
    intake_result: ApplicationIntakeResult,
    created_artifacts: tuple[str, ...],
    pending_artifacts: tuple[str, ...],
    skipped_stages: tuple[str, ...],
) -> None:
    append_jsonl(
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


def append_end_to_end_audit_log_section(
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
        "\n## LangGraph Orchestration Flow\n\n"
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
        f"- Next step: {end_to_end_next_step_for(status)}\n\n"
        "### Created artifacts\n\n"
        f"{created_lines}\n"
        "### Pending artifacts\n\n"
        f"{pending_lines}\n"
        "### Skipped stages\n\n"
        f"{skipped_lines}"
    )

    with (scaffold.artifacts_dir / "audit_log.md").open("a", encoding="utf-8") as file:
        file.write(section)


def read_workflow_artifacts(path: Path) -> WorkflowArtifacts:
    payload = read_json_object(path)
    manifest = RunArtifactManifest.model_validate(payload)

    created: list[str] = []
    pending: list[str] = []

    for key, artifact in sorted(manifest.artifacts.items()):
        if artifact.status == ArtifactStatus.CREATED:
            created.append(key)
        else:
            pending.append(key)

    return WorkflowArtifacts(created=tuple(created), pending=tuple(pending))


def append_failure_audit_event(*, scaffold: RunScaffold, error: str) -> None:
    append_jsonl(
        scaffold.logs_dir / "audit_events.jsonl",
        {
            "event": "langgraph_workflow_failed",
            "run_id": scaffold.run_id,
            "status": "failed",
            "error": error,
        },
    )


def set_run_metadata_status(scaffold: RunScaffold, status: RunStatus) -> None:
    payload = read_json_object(scaffold.metadata_path)
    metadata = RunMetadata.model_validate(payload)
    updated = metadata.model_copy(update={"status": status})
    write_json(scaffold.metadata_path, updated)
