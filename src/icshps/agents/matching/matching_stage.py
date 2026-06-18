from __future__ import annotations

from pathlib import Path
from collections.abc import Sequence

from icshps.agents.matching.jd_matching_agent import match_candidate_to_job
from icshps.schemas import (
    BundleContext,
    JobMatchRequirements,
    MatchResultsArtifact,
    CandidateProfile,
)

from icshps.services import (
    RunScaffold,
    AgentStageResult,
    read_candidate_profiles,
    write_json_artifact,
)
from icshps.utils.file_io import read_yaml_object
from icshps.utils.text import optional_float, string_list


def run_matching_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
    candidate_profiles: Sequence[CandidateProfile] | None = None,
) -> AgentStageResult:
    """Run the orchestration-facing JD matching artifact stage."""

    profiles = (
        list(candidate_profiles)
        if candidate_profiles is not None
        else read_candidate_profiles(scaffold)
    )
    if not profiles:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("match_scores",),
            warnings=(
                "Match score stage skipped because candidate profile artifacts were not "
                "created.",
            ),
        )

    try:
        requirements = _load_job_match_requirements(
            skills_matrix_path=context.required_inputs.skills_matrix,
            job_id=context.job.id,
        )
        results = [
            match_candidate_to_job(candidate_profile, requirements)
            for candidate_profile in sorted(
                profiles,
                key=lambda profile: (profile.candidate_id, profile.application_id),
            )
        ]
        artifact = MatchResultsArtifact(run_id=scaffold.run_id, results=results)

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("match_scores",),
            warnings=(
                f"Match score stage skipped after controlled matching error: {exc}",
            ),
        )

    artifact_path = write_json_artifact(
        scaffold=scaffold,
        artifact_key="match_scores",
        payload=artifact,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("match_scores",),
        skipped_stages=(),
        warnings=(),
    )


def _load_job_match_requirements(
    *,
    skills_matrix_path: Path,
    job_id: str,
) -> JobMatchRequirements:
    if not skills_matrix_path.exists() or skills_matrix_path.stat().st_size == 0:
        return JobMatchRequirements(job_id=job_id)

    payload = read_yaml_object(skills_matrix_path)

    return JobMatchRequirements(
        job_id=job_id,
        must_have=string_list(
            payload.get("must_have") or payload.get("must_have_skills") or []
        ),
        nice_to_have=string_list(
            payload.get("nice_to_have") or payload.get("nice_to_have_skills") or []
        ),
        minimum_years_experience=optional_float(
            payload.get("minimum_years_experience")
            or payload.get("min_years_experience")
        ),
        mandatory_certifications=string_list(
            payload.get("mandatory_certifications")
            or payload.get("required_certifications")
            or payload.get("certifications")
            or []
        ),
    )
