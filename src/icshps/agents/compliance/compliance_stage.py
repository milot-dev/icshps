from __future__ import annotations

from icshps.agents.compliance.eeo_agent import build_eeo_compliance_findings
from icshps.schemas import BundleContext, FindingsArtifact
from icshps.services import (
    artifact_path,
    mark_artifacts_created,
    read_json_artifact,
    write_compliance_flags_md,
    RunScaffold,
    AgentStageResult
)

def run_compliance_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
) -> AgentStageResult:
    """Run the orchestration-facing EEO/compliance flags artifact stage."""

    try:
        eeo_artifact = build_eeo_compliance_findings(
            run_id=scaffold.run_id,
            job_description_path=context.required_inputs.job_description,
            job_title=context.job.title,
            eeo_policy_path=context.required_inputs.eeo_policy,
        )

        verification_payload = read_json_artifact(
            scaffold=scaffold,
            artifact_key="verification_findings",
        )
        verification_artifact = (
            FindingsArtifact.model_validate(verification_payload)
            if verification_payload is not None
            else FindingsArtifact(run_id=scaffold.run_id, findings=[])
        )

        combined = FindingsArtifact(
            run_id=scaffold.run_id,
            findings=[*eeo_artifact.findings, *verification_artifact.findings],
        )

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("compliance_flags",),
            warnings=(
                "Compliance flags stage skipped after controlled compliance error: "
                f"{exc}",
            ),
        )

    output_path = artifact_path(scaffold, "compliance_flags")
    write_compliance_flags_md(output_path, combined)
    mark_artifacts_created(
        scaffold=scaffold,
        artifact_keys=("compliance_flags",),
    )

    return AgentStageResult(
        path=output_path,
        created_artifacts=("compliance_flags",),
        skipped_stages=(),
        warnings=(),
    )
