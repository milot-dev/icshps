from __future__ import annotations

from collections.abc import Sequence

from icshps.agents.verification.credential_verification_agent import (
    build_credential_verification_findings,
    build_mandatory_certification_findings,
)
from icshps.agents.verification.linkedin_consistency_agent import (
    build_linkedin_consistency_findings,
)
from icshps.schemas import BundleContext, CandidateProfile, FindingsArtifact
from icshps.services import (
    RunScaffold,
    AgentStageResult,
    read_json_artifact,
    write_json_artifact,
)


def run_verification_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
    candidate_profiles: Sequence[CandidateProfile] | None = None,
) -> AgentStageResult:
    """Run the orchestration-facing credential verification artifact stage."""

    profiles = list(candidate_profiles) if candidate_profiles is not None else _read_candidate_profiles(scaffold)
    if not profiles:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("verification_findings",),
            warnings=(
                "Verification stage skipped because candidate profile artifacts were not "
                "created.",
            ),
        )

    try:
        artifact = FindingsArtifact(run_id=scaffold.run_id)
        for candidate_profile in sorted(
            profiles,
            key=lambda profile: (profile.candidate_id, profile.application_id),
        ):
            mandatory_artifact = build_mandatory_certification_findings(
                run_id=scaffold.run_id,
                candidate_profile=candidate_profile,
                skills_matrix_path=context.required_inputs.skills_matrix,
            )
            credential_artifact = build_credential_verification_findings(
                run_id=scaffold.run_id,
                candidate_profile=candidate_profile,
                credential_evidence_path=context.optional_inputs.credential_evidence,
            )
            linkedin_artifact = build_linkedin_consistency_findings(
                run_id=scaffold.run_id,
                candidate_profile=candidate_profile,
                linkedin_profiles_path=context.optional_inputs.linkedin_profiles,
            )
            artifact.findings.extend(mandatory_artifact.findings)
            artifact.findings.extend(credential_artifact.findings)
            artifact.findings.extend(linkedin_artifact.findings)

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("verification_findings",),
            warnings=(
                "Verification stage skipped after controlled certification check "
                f"error: {exc}",
            ),
        )

    artifact_path = write_json_artifact(
        scaffold=scaffold,
        artifact_key="verification_findings",
        payload=artifact,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("verification_findings",),
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
