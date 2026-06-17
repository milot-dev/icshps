from __future__ import annotations

from collections.abc import Sequence

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
    candidate_profiles: Sequence[CandidateProfile] | None = None,
) -> AgentStageResult:
    """Run the orchestration-facing anomaly findings artifact stage."""

    try:
        profiles = list(candidate_profiles) if candidate_profiles is not None else _read_candidate_profiles(scaffold)
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


def _read_candidate_profiles(scaffold: RunScaffold) -> list[CandidateProfile]:
    profile_payload = read_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
    )
    if profile_payload is None:
        return []

    return [CandidateProfile.model_validate(profile_payload)]
