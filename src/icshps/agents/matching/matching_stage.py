from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

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
    read_json_artifact,
    write_json_artifact,
)


def run_matching_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
) -> AgentStageResult:
    """Run the orchestration-facing JD matching artifact stage."""

    profile_payload = read_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
    )
    if profile_payload is None:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("match_scores",),
            warnings=(
                "Match score stage skipped because candidate_profile.json was not "
                "created.",
            ),
        )

    try:
        candidate_profile = CandidateProfile.model_validate(profile_payload)
        requirements = _load_job_match_requirements(
            skills_matrix_path=context.required_inputs.skills_matrix,
            job_id=context.job.id,
        )
        result = match_candidate_to_job(candidate_profile, requirements)
        artifact = MatchResultsArtifact(run_id=scaffold.run_id, results=[result])

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("match_scores",),
            warnings=(
                "Match score stage skipped after controlled matching error: " f"{exc}",
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

    payload = yaml.safe_load(skills_matrix_path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        return JobMatchRequirements(job_id=job_id)

    return JobMatchRequirements(
        job_id=job_id,
        must_have=_string_list(
            payload.get("must_have") or payload.get("must_have_skills") or []
        ),
        nice_to_have=_string_list(
            payload.get("nice_to_have") or payload.get("nice_to_have_skills") or []
        ),
        minimum_years_experience=_optional_float(
            payload.get("minimum_years_experience")
            or payload.get("min_years_experience")
        ),
        mandatory_certifications=_string_list(
            payload.get("mandatory_certifications")
            or payload.get("required_certifications")
            or payload.get("certifications")
            or []
        ),
    )


def _string_list(raw_value: Any) -> list[str]:
    if raw_value is None:
        return []

    if isinstance(raw_value, str):
        return [raw_value.strip()] if raw_value.strip() else []

    if not isinstance(raw_value, list):
        return []

    values: list[str] = []
    for item in raw_value:
        if isinstance(item, str):
            value = item.strip()
        elif isinstance(item, dict):
            value = str(item.get("name") or item.get("label") or "").strip()
        else:
            value = str(item).strip()

        if value:
            values.append(value)

    return values


def _optional_float(raw_value: Any) -> float | None:
    if raw_value in (None, ""):
        return None

    try:
        return float(raw_value)
    except (TypeError, ValueError):
        return None
