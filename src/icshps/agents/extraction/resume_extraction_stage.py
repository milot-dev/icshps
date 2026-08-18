from __future__ import annotations


from icshps.agents.extraction.pdf_text_extractor import extract_pdf_text
from icshps.agents.extraction.pdf_bounding_boxes import use_vision_page_index
from icshps.agents.extraction.llm_recovery import LLMRecoveryMetrics
from icshps.agents.extraction.resume_extraction_agent import (
    VISION_OCR_REVIEW_FLAG,
    extract_candidate_profile,
)
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
    ocr_metrics_by_candidate: dict[str, dict] = {}

    for candidate in candidates:
        candidate_metric_key = f"{candidate.id}:{candidate.application_id}"
        candidate_llm_metrics: dict = {}
        try:
            extraction_result = extract_pdf_text(candidate.resume_file)
            ocr_metrics_by_candidate[candidate_metric_key] = (
                extraction_result.ocr_metrics()
            )

            if extraction_result.ok:
                warnings.extend(
                    f"{candidate.id}: {issue}" for issue in extraction_result.issues
                )
                with use_vision_page_index(
                    candidate.resume_file,
                    extraction_result.pages,
                ):
                    profile = extract_candidate_profile(
                        extraction_result.text,
                        candidate_id=candidate.id,
                        application_id=candidate.application_id,
                        role_id=candidate.target_job_id,
                        source_file=candidate.resume_file,
                        llm_metrics=candidate_llm_metrics,
                        ocr_manual_review_required=(
                            extraction_result.ocr_manual_review_required
                        ),
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
                if (
                    extraction_result.ocr_manual_review_required
                    and VISION_OCR_REVIEW_FLAG not in profile.manual_review_flags
                ):
                    profile.manual_review_flags.append(VISION_OCR_REVIEW_FLAG)
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
    write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profiles",
        payload=[profile.model_dump(mode="json") for profile in profiles],
    )
    _update_extraction_metrics(
        scaffold=scaffold,
        llm_metrics_by_candidate=llm_metrics_by_candidate,
        ocr_metrics_by_candidate=ocr_metrics_by_candidate,
    )

    return AgentStageResult(
        path=artifact_path,
        created_artifacts=("candidate_profile", "candidate_profiles"),
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
    ocr_metrics_by_candidate: dict[str, dict],
) -> None:
    metrics_path = scaffold.artifacts_dir / "metrics.json"
    metrics = read_json_object(metrics_path, default_empty=True)
    artifacts_created = set(metrics.get("artifacts_created", []))
    artifacts_created.add("artifacts/candidate_profile.json")
    artifacts_created.add("artifacts/candidate_profiles.json")

    llm_records = list(llm_metrics_by_candidate.values())
    ocr_records = list(ocr_metrics_by_candidate.values())
    ocr_attempted_page_count = sum(
        int(record.get("attempted_page_count", 0)) for record in ocr_records
    )
    recovery_call_count = sum(
        1 for record in llm_records if record.get("called") is True
    )
    providers_used = sorted(
        {
            str(record["provider"])
            for record in ocr_records
            if record.get("attempted") is True and record.get("provider")
        }
        | {
            str(record["provider"])
            for record in llm_records
            if record.get("called") is True and record.get("provider")
        }
    )
    metrics["llm_enabled"] = any(
        record.get("enabled", False) for record in [*ocr_records, *llm_records]
    )
    metrics["llm_provider_used"] = ",".join(providers_used) if providers_used else None
    metrics["llm_resume_extraction_calls"] = (
        ocr_attempted_page_count + recovery_call_count
    )
    metrics["scanned_resume_detected_count"] = sum(
        1 for record in ocr_records if record.get("scan_detected") is True
    )
    metrics["extraction"] = {
        "candidate_profile_written": True,
        "candidate_profiles_written": True,
        "candidate_count": len(llm_records),
        "artifact_paths": [
            "artifacts/candidate_profile.json",
            "artifacts/candidate_profiles.json",
        ],
        "ocr": {
            "enabled": any(record.get("enabled", False) for record in ocr_records),
            "available": any(record.get("available") is True for record in ocr_records),
            "attempted": any(record.get("attempted", False) for record in ocr_records),
            "succeeded": any(
                int(record.get("succeeded_page_count", 0)) > 0 for record in ocr_records
            ),
            "attempted_page_count": ocr_attempted_page_count,
            "succeeded_page_count": sum(
                int(record.get("succeeded_page_count", 0)) for record in ocr_records
            ),
            "failed_page_count": sum(
                int(record.get("failed_page_count", 0)) for record in ocr_records
            ),
            "scan_detected": any(
                record.get("scan_detected", False) for record in ocr_records
            ),
            "scan_detected_page_count": sum(
                int(record.get("scan_detected_page_count", 0))
                for record in ocr_records
            ),
            "provider": next(
                (
                    str(record["provider"])
                    for record in ocr_records
                    if record.get("provider")
                ),
                None,
            ),
            "manual_review_required": any(
                record.get("manual_review_required") is True for record in ocr_records
            ),
            "statuses": sorted(
                {str(record.get("status", "not_needed")) for record in ocr_records}
            ),
            "extraction_methods": sorted(
                {
                    str(method)
                    for record in ocr_records
                    for method in record.get("extraction_methods", [])
                }
            ),
            "by_candidate": ocr_metrics_by_candidate,
        },
        "llm_recovery": {
            "enabled": any(record.get("enabled", False) for record in llm_records),
            "available": any(record.get("available", False) for record in llm_records),
            "called": any(record.get("called", False) for record in llm_records),
            "providers": sorted(
                {
                    str(record["provider"])
                    for record in llm_records
                    if record.get("called") is True and record.get("provider")
                }
            ),
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
                int(record.get("manual_review_flag_count", 0)) for record in llm_records
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
