from __future__ import annotations


from icshps.agents.extraction.pdf_text_extractor import extract_pdf_text
from icshps.agents.extraction.resume_extraction_agent import extract_candidate_profile
from icshps.agents.extraction.synthetic_profile_fallback import (
    build_synthetic_candidate_profile,
)
from icshps.schemas import BundleContext, CandidateApplication
from icshps.services import RunScaffold, AgentStageResult, write_json_artifact


def run_resume_extraction_stage(
    *,
    scaffold: RunScaffold,
    context: BundleContext,
) -> AgentStageResult:
    """Run the orchestration-facing resume extraction/profile artifact stage."""

    candidates = _ordered_candidates(context)
    if not candidates:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("candidate_profile",),
            warnings=(
                "Candidate profile stage skipped because the bundle has no candidates.",
            ),
        )

    candidate = candidates[0]
    warnings: list[str] = []

    if len(candidates) > 1:
        warnings.append(
            "Only the first candidate was written to candidate_profile.json because "
            "the current shared contract is CandidateProfile, not a multi-candidate list."
        )

    try:
        extraction_result = extract_pdf_text(candidate.resume_file)

        if extraction_result.ok:
            profile = extract_candidate_profile(
                extraction_result.text,
                candidate_id=candidate.id,
                application_id=candidate.application_id,
                role_id=candidate.target_job_id,
                source_file=candidate.resume_file,
            )
        else:
            reason = (
                f"PDF text extraction returned status '{extraction_result.status}'. "
                f"Issues: {'; '.join(extraction_result.issues) or 'none recorded'}"
            )
            warnings.append(reason)

            profile = build_synthetic_candidate_profile(
                candidate_id=candidate.id,
                application_id=candidate.application_id,
                role_id=candidate.target_job_id,
                source_file=candidate.resume_file,
                reason=reason,
            )

    except Exception as exc:
        return AgentStageResult(
            path=None,
            created_artifacts=(),
            skipped_stages=("candidate_profile",),
            warnings=(
                "Candidate profile stage skipped after controlled extraction error: "
                f"{exc}",
            ),
        )

    artifact_path = write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
        payload=profile,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("candidate_profile",),
        skipped_stages=(),
        warnings=tuple(warnings),
    )


def _ordered_candidates(context: BundleContext) -> list[CandidateApplication]:
    return sorted(
        context.candidates,
        key=lambda candidate: (candidate.id, candidate.application_id),
    )
