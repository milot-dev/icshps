from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from langgraph.graph import END, START, StateGraph

from icshps.agents.anomaly import run_anomaly_stage
from icshps.agents.compliance import run_compliance_stage
from icshps.agents.extraction import run_resume_extraction_stage
from icshps.agents.intake import run_application_intake
from icshps.agents.matching import run_matching_stage
from icshps.agents.orchestrator import build_final_decision_from_run
from icshps.agents.scheduling import run_interview_schedule_stage
from icshps.agents.triage import build_exception_triage_findings
from icshps.agents.verification import run_verification_stage
from icshps.graph.finalization import (
    append_end_to_end_audit_event,
    append_end_to_end_audit_log_section,
    append_failure_audit_event,
    end_to_end_next_step_for,
    read_workflow_artifacts,
    set_run_metadata_status,
    update_end_to_end_metrics,
)
from icshps.graph.result import EndToEndWorkflowResult
from icshps.graph.state import WorkflowState
from icshps.schemas import FindingsArtifact, RunStatus
from icshps.services import (
    artifact_path,
    load_hiring_bundle,
    mark_artifacts_created,
    prepare_run_scaffold,
    write_compliance_flags_md,
    write_final_run_artifacts,
)

DOWNSTREAM_ARTIFACT_STAGES: tuple[str, ...] = (
    "candidate_profile",
    "candidate_profiles",
    "match_scores",
    "compliance_flags",
    "verification_findings",
    "anomaly_findings",
    "fraud_findings",
)


def build_langgraph_workflow() -> Any:
    """Build the minimal LangGraph orchestration graph for the MVP pipeline."""

    graph = StateGraph(WorkflowState)

    graph.add_node("prepare_run", prepare_run_node)
    graph.add_node("intake", intake_node)
    graph.add_node("resume_extraction", resume_extraction_node)
    graph.add_node("matching", matching_node)
    graph.add_node("verification", verification_node)
    graph.add_node("compliance", compliance_node)
    graph.add_node("anomaly_detection", anomaly_detection_node)
    graph.add_node("routing_and_final_artifacts", routing_and_final_artifacts_node)
    graph.add_node("finalize_completed", finalize_completed_node)
    graph.add_node("finalize_blocked", finalize_blocked_node)

    graph.add_edge(START, "prepare_run")
    graph.add_edge("prepare_run", "intake")
    graph.add_conditional_edges(
        "intake",
        route_after_intake,
        {
            "continue": "resume_extraction",
            "blocked": "finalize_blocked",
        },
    )
    graph.add_edge("resume_extraction", "matching")
    graph.add_edge("matching", "verification")
    graph.add_edge("verification", "compliance")
    graph.add_edge("compliance", "anomaly_detection")
    graph.add_edge("anomaly_detection", "routing_and_final_artifacts")
    graph.add_edge("routing_and_final_artifacts", "finalize_completed")
    graph.add_edge("finalize_completed", END)
    graph.add_edge("finalize_blocked", END)

    return graph.compile()


def run_langgraph_workflow(
    bundle_path: str | Path,
    *,
    runs_root: str | Path = Path("runs"),
    run_id: str | None = None,
    reset: bool = True,
) -> EndToEndWorkflowResult:
    """Run the deterministic backend pipeline through LangGraph orchestration."""

    initial_state: WorkflowState = {
        "bundle_path": Path(bundle_path),
        "runs_root": Path(runs_root),
        "run_id": run_id,
        "reset": reset,
        "ready_for_downstream": False,
        "created_artifacts": (),
        "pending_artifacts": (),
        "skipped_stages": (),
        "warnings": (),
        "errors": (),
    }

    final_state: WorkflowState = {**initial_state}

    try:
        for update_chunk in build_langgraph_workflow().stream(initial_state):
            for update in update_chunk.values():
                final_state.update(update)
        return _result_from_state(final_state)

    except Exception as exc:
        return _failed_result_from_state(final_state, error=str(exc))


def prepare_run_node(state: WorkflowState) -> WorkflowState:
    scaffold = prepare_run_scaffold(
        bundle_path=Path(state["bundle_path"]),
        runs_root=Path(state["runs_root"]),
        run_id=state.get("run_id"),
        reset=state.get("reset", True),
    )
    set_run_metadata_status(scaffold, RunStatus.RUNNING)

    loaded_bundle = load_hiring_bundle(state["bundle_path"], run_id=scaffold.run_id)

    return {
        "run_id": scaffold.run_id,
        "scaffold": scaffold,
        "loaded_bundle": loaded_bundle,
        "context": loaded_bundle.context,
        "artifact_manifest_path": scaffold.artifact_manifest_path,
        "metrics_path": scaffold.artifacts_dir / "metrics.json",
        "audit_log_path": scaffold.artifacts_dir / "audit_log.md",
    }


def intake_node(state: WorkflowState) -> WorkflowState:
    scaffold = _required(state, "scaffold")
    loaded_bundle = _required(state, "loaded_bundle")

    intake_result = run_application_intake(
        loaded_bundle=loaded_bundle,
        scaffold=scaffold,
    )

    return {
        "intake_result": intake_result,
        "context": loaded_bundle.context,
        "context_packet_path": intake_result.context_packet_path,
        "intake_findings_path": intake_result.intake_findings_path,
        "ready_for_downstream": intake_result.ready_for_downstream,
        "warnings": _append_values(state, "warnings", intake_result.warnings),
        "errors": _append_values(state, "errors", intake_result.errors),
    }


def route_after_intake(state: WorkflowState) -> Literal["continue", "blocked"]:
    if state.get("ready_for_downstream") and state.get("context") is not None:
        return "continue"

    return "blocked"


def resume_extraction_node(state: WorkflowState) -> WorkflowState:
    stage = run_resume_extraction_stage(
        scaffold=_required(state, "scaffold"),
        context=_required(state, "context"),
    )
    candidate_profiles = (
        tuple(stage.payload) if isinstance(stage.payload, list) else ()
    )

    return {
        "candidate_profile_path": stage.path,
        "candidate_profiles": candidate_profiles,
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", stage.warnings),
    }


def matching_node(state: WorkflowState) -> WorkflowState:
    stage = run_matching_stage(
        scaffold=_required(state, "scaffold"),
        context=_required(state, "context"),
        candidate_profiles=state.get("candidate_profiles", ()),
    )

    return {
        "match_scores_path": stage.path,
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", stage.warnings),
    }


def verification_node(state: WorkflowState) -> WorkflowState:
    stage = run_verification_stage(
        scaffold=_required(state, "scaffold"),
        context=_required(state, "context"),
        candidate_profiles=state.get("candidate_profiles", ()),
    )

    return {
        "verification_findings_path": stage.path,
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", stage.warnings),
    }


def compliance_node(state: WorkflowState) -> WorkflowState:
    stage = run_compliance_stage(
        scaffold=_required(state, "scaffold"),
        context=_required(state, "context"),
    )

    return {
        "compliance_flags_path": stage.path,
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", stage.warnings),
    }


def anomaly_detection_node(state: WorkflowState) -> WorkflowState:
    scaffold = _required(state, "scaffold")
    stage = run_anomaly_stage(
        scaffold=scaffold,
        context=_required(state, "context"),
        candidate_profiles=state.get("candidate_profiles", ()),
    )

    return {
        "anomaly_findings_path": stage.path,
        "fraud_findings_path": (
            scaffold.artifacts_dir / "fraud_findings.json"
            if "fraud_findings" in stage.created_artifacts
            else None
        ),
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", stage.warnings),
    }


def routing_and_final_artifacts_node(state: WorkflowState) -> WorkflowState:
    scaffold = _required(state, "scaffold")
    candidate_profiles = state.get("candidate_profiles", ())

    final_decision = build_final_decision_from_run(
        scaffold,
        candidate_profiles=candidate_profiles,
    )
    triage_artifact = build_exception_triage_findings(
        final_decision=final_decision,
    )
    final_decision = final_decision.model_copy(
        update={
            "findings": [*final_decision.findings, *triage_artifact.findings],
            "summary": (
                f"{final_decision.summary or ''} "
                f"Added {len(triage_artifact.findings)} triage finding(s)."
            ).strip(),
        }
    )

    compliance_flags_path = artifact_path(scaffold, "compliance_flags")
    write_compliance_flags_md(
        compliance_flags_path,
        FindingsArtifact(
            run_id=scaffold.run_id,
            findings=final_decision.findings,
        ),
    )
    mark_artifacts_created(
        scaffold=scaffold,
        artifact_keys=("compliance_flags",),
    )
    write_final_run_artifacts(
        scaffold=scaffold,
        final_decision=final_decision,
        candidate_profiles=list(candidate_profiles),
    )
    schedule_stage = run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
    )

    return {
        "final_decision": final_decision,
        "compliance_flags_path": compliance_flags_path,
        "interview_schedule_path": schedule_stage.path,
        "skipped_stages": _append_values(
            state,
            "skipped_stages",
            schedule_stage.skipped_stages,
        ),
        "warnings": _append_values(state, "warnings", schedule_stage.warnings),
    }


def finalize_completed_node(state: WorkflowState) -> WorkflowState:
    return _finalize_state(state, status="completed")


def finalize_blocked_node(state: WorkflowState) -> WorkflowState:
    return _finalize_state(
        {
            **state,
            "skipped_stages": _append_values(
                state,
                "skipped_stages",
                DOWNSTREAM_ARTIFACT_STAGES,
            ),
        },
        status="blocked",
    )


def _finalize_state(
    state: WorkflowState,
    *,
    status: Literal["completed", "blocked"],
) -> WorkflowState:
    scaffold = _required(state, "scaffold")
    loaded_bundle = _required(state, "loaded_bundle")
    intake_result = _required(state, "intake_result")

    artifacts = read_workflow_artifacts(scaffold.artifact_manifest_path)
    skipped = tuple(sorted(set(state.get("skipped_stages", ()))))

    update_end_to_end_metrics(
        scaffold=scaffold,
        loaded_bundle=loaded_bundle,
        status=status,
        created_artifacts=artifacts.created,
        skipped_stages=skipped,
    )
    append_end_to_end_audit_event(
        scaffold=scaffold,
        status=status,
        intake_result=intake_result,
        created_artifacts=artifacts.created,
        pending_artifacts=artifacts.pending,
        skipped_stages=skipped,
    )
    append_end_to_end_audit_log_section(
        scaffold=scaffold,
        status=status,
        created_artifacts=artifacts.created,
        pending_artifacts=artifacts.pending,
        skipped_stages=skipped,
    )
    set_run_metadata_status(scaffold, RunStatus.COMPLETED)

    return {
        "status": status,
        "created_artifacts": artifacts.created,
        "pending_artifacts": artifacts.pending,
        "skipped_stages": skipped,
        "warnings": tuple(dict.fromkeys(state.get("warnings", ()))),
        "errors": tuple(dict.fromkeys(state.get("errors", ()))),
    }


def _result_from_state(state: WorkflowState) -> EndToEndWorkflowResult:
    scaffold = state.get("scaffold")
    status = state.get("status", "failed")

    return EndToEndWorkflowResult(
        status=status,
        ready_for_downstream=state.get("ready_for_downstream", False),
        run_id=scaffold.run_id if scaffold is not None else state.get("run_id"),
        run_dir=scaffold.run_dir if scaffold is not None else None,
        context_packet_path=state.get("context_packet_path"),
        intake_findings_path=state.get("intake_findings_path"),
        candidate_profile_path=state.get("candidate_profile_path"),
        match_scores_path=state.get("match_scores_path"),
        compliance_flags_path=state.get("compliance_flags_path"),
        verification_findings_path=state.get("verification_findings_path"),
        anomaly_findings_path=state.get("anomaly_findings_path"),
        fraud_findings_path=state.get("fraud_findings_path"),
        interview_schedule_path=state.get("interview_schedule_path"),
        final_decision=state.get("final_decision"),
        artifact_manifest_path=state.get("artifact_manifest_path"),
        metrics_path=state.get("metrics_path"),
        audit_log_path=state.get("audit_log_path"),
        created_artifacts=state.get("created_artifacts", ()),
        pending_artifacts=state.get("pending_artifacts", ()),
        skipped_stages=state.get("skipped_stages", ()),
        warnings=state.get("warnings", ()),
        errors=state.get("errors", ()),
        next_step=end_to_end_next_step_for(status),
    )


def _failed_result_from_state(
    state: WorkflowState,
    *,
    error: str,
) -> EndToEndWorkflowResult:
    scaffold = state.get("scaffold")

    if scaffold is not None:
        append_failure_audit_event(scaffold=scaffold, error=error)
        set_run_metadata_status(scaffold, RunStatus.FAILED)
        artifacts = read_workflow_artifacts(scaffold.artifact_manifest_path)
        state = {
            **state,
            "status": "failed",
            "created_artifacts": artifacts.created,
            "pending_artifacts": artifacts.pending,
            "errors": (error,),
        }
        return _result_from_state(state)

    return EndToEndWorkflowResult(
        status="failed",
        ready_for_downstream=False,
        run_id=state.get("run_id"),
        run_dir=None,
        context_packet_path=None,
        intake_findings_path=None,
        candidate_profile_path=None,
        match_scores_path=None,
        compliance_flags_path=None,
        verification_findings_path=None,
        anomaly_findings_path=None,
        fraud_findings_path=None,
        interview_schedule_path=None,
        final_decision=None,
        artifact_manifest_path=None,
        metrics_path=None,
        audit_log_path=None,
        created_artifacts=(),
        pending_artifacts=(),
        skipped_stages=(),
        warnings=(),
        errors=(error,),
        next_step=end_to_end_next_step_for("failed"),
    )


def _append_values(
    state: WorkflowState,
    key: Literal["errors", "skipped_stages", "warnings"],
    values: tuple[str, ...],
) -> tuple[str, ...]:
    return (*state.get(key, ()), *values)


def _required(state: WorkflowState, key: str) -> Any:
    value = state.get(key)
    if value is None:
        raise ValueError(f"LangGraph workflow state is missing required key: {key}")

    return value
