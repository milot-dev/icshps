from __future__ import annotations

from icshps.agents.anomaly.anomaly_detection_agent import build_anomaly_findings
from icshps.schemas import BundleContext, CandidateProfile
from icshps.services import (
    AgentStageResult,
    RunScaffold,
    read_json_artifact,
    write_json_artifact,
)


def run_anomaly_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
) -> AgentStageResult:
    """Run the orchestration-facing anomaly findings artifact stage."""

    try:
        profile_payload = read_json_artifact(
            scaffold=scaffold,
            artifact_key="candidate_profile",
        )
        profiles = (
            [CandidateProfile.model_validate(profile_payload)]
            if profile_payload is not None
            else []
        )
        artifact = build_anomaly_findings(
            run_id=scaffold.run_id,
            candidate_profiles=profiles,
            application_history_path=context.optional_inputs.application_history,
            application_volume_path=context.optional_inputs.application_volume,
        )

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("anomaly_findings",),
            warnings=(
                "Anomaly stage skipped after controlled anomaly error: "
                f"{exc}",
            ),
        )

    artifact_path = write_json_artifact(
        scaffold=scaffold,
        artifact_key="anomaly_findings",
        payload=artifact,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("anomaly_findings",),
        skipped_stages=(),
        warnings=(),
    )
