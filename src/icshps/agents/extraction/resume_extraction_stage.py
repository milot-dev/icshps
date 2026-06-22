from __future__ import annotations


from icshps.agents.extraction.pdf_text_extractor import extract_pdf_text
from icshps.agents.extraction.llm_recovery import LLMRecoveryMetrics
from icshps.agents.extraction.resume_extraction_agent import extract_candidate_profile
from icshps.agents.extraction.synthetic_profile_fallback import (
    build_synthetic_candidate_profile,
)
from icshps.schemas import BundleContext, CandidateApplication, CandidateProfile
from icshps.services import RunScaffold, AgentStageResult, write_json_artifact
from icshps.utils.file_io import read_json_object, write_json


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

    warnings: list[str] = []
    profiles: list[CandidateProfile] = []
    llm_metrics_by_candidate: dict[str, dict] = {}

    for candidate in candidates:
        candidate_metric_key = f"{candidate.id}:{candidate.application_id}"
        candidate_llm_metrics: dict = {}
        try:
            extraction_result = extract_pdf_text(candidate.resume_file)

            if extraction_result.ok:
                profile = extract_candidate_profile(
                    extraction_result.text,
                    candidate_id=candidate.id,
                    application_id=candidate.application_id,
                    role_id=candidate.target_job_id,
                    source_file=candidate.resume_file,
                    llm_metrics=candidate_llm_metrics,
                )
            else:
                reason = (
                    f"PDF text extraction returned status '{extraction_result.status}' "
                    f"for {candidate.id}. Issues: "
                    f"{'; '.join(extraction_result.issues) or 'none recorded'}"
                )
                warnings.append(reason)

                profile = build_synthetic_candidate_profile(
                    candidate_id=candidate.id,
                    application_id=candidate.application_id,
                    role_id=candidate.target_job_id,
                    source_file=candidate.resume_file,
                    reason=reason,
                )
                candidate_llm_metrics = LLMRecoveryMetrics(
                    skipped_reason="pdf_text_extraction_failed",
                    final_extraction_mode="synthetic_fallback",
                    manual_review_flag_count=len(profile.manual_review_flags),
                ).as_dict()
            profiles.append(profile)
            llm_metrics_by_candidate[candidate_metric_key] = (
                candidate_llm_metrics or LLMRecoveryMetrics().as_dict()
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

    profile = profiles[0]

    artifact_path = write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profile",
        payload=profile,
    )
    _update_extraction_metrics(
        scaffold=scaffold,
        llm_metrics_by_candidate=llm_metrics_by_candidate,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("candidate_profile",),
        skipped_stages=(),
        warnings=tuple(warnings),
        payload=profiles,
    )


def _ordered_candidates(context: BundleContext) -> list[CandidateApplication]:
    return sorted(
        context.candidates,
        key=lambda candidate: (candidate.id, candidate.application_id),
    )


def _update_extraction_metrics(
    *,
    scaffold: RunScaffold,
    llm_metrics_by_candidate: dict[str, dict],
) -> None:
    metrics_path = scaffold.artifacts_dir / "metrics.json"
    metrics = read_json_object(metrics_path, default_empty=True)
    artifacts_created = set(metrics.get("artifacts_created", []))
    artifacts_created.add("artifacts/candidate_profile.json")

    llm_records = list(llm_metrics_by_candidate.values())
    metrics["extraction"] = {
        "candidate_profile_written": True,
        "candidate_count": len(llm_records),
        "llm_recovery": {
            "enabled": any(record.get("enabled", False) for record in llm_records),
            "available": any(record.get("available", False) for record in llm_records),
            "called": any(record.get("called", False) for record in llm_records),
            "trigger_reasons": sorted(
                {
                    reason
                    for record in llm_records
                    for reason in record.get("trigger_reasons", [])
                }
            ),
            "accepted_field_count": sum(
                int(record.get("accepted_field_count", 0)) for record in llm_records
            ),
            "rejected_field_count": sum(
                int(record.get("rejected_field_count", 0)) for record in llm_records
            ),
            "validation_error_count": sum(
                int(record.get("validation_error_count", 0)) for record in llm_records
            ),
            "recommendation_violation_count": sum(
                int(record.get("recommendation_violation_count", 0))
                for record in llm_records
            ),
            "manual_review_flag_count": sum(
                int(record.get("manual_review_flag_count", 0))
                for record in llm_records
            ),
            "final_extraction_modes": sorted(
                {
                    record.get("final_extraction_mode", "deterministic")
                    for record in llm_records
                }
            ),
            "by_candidate": llm_metrics_by_candidate,
        },
    }
    metrics["artifacts_created"] = sorted(artifacts_created)

    write_json(metrics_path, metrics)
