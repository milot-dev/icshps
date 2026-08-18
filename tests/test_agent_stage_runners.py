from __future__ import annotations

from pathlib import Path

from icshps.agents.anomaly import run_anomaly_stage
from icshps.agents.compliance import run_compliance_stage
from icshps.agents.extraction import run_resume_extraction_stage
from icshps.agents.extraction import resume_extraction_stage
from icshps.agents.extraction.pdf_text_extractor import (
    ExtractedPDFPage,
    PDFTextExtractionResult,
)
from icshps.agents.intake import run_application_intake
from icshps.agents.matching import run_matching_stage
from icshps.agents.verification import run_verification_stage
from icshps.services import load_hiring_bundle
from icshps.services import prepare_run_scaffold

from test_end_to_end_workflow import build_bundle, read_json


def test_agent_stage_runners_create_expected_artifacts(tmp_path: Path) -> None:
    scaffold, context = prepare_ready_context(tmp_path)

    profile_stage = run_resume_extraction_stage(scaffold=scaffold, context=context)
    matching_stage = run_matching_stage(scaffold=scaffold, context=context)
    verification_stage = run_verification_stage(scaffold=scaffold, context=context)
    compliance_stage = run_compliance_stage(scaffold=scaffold, context=context)
    anomaly_stage = run_anomaly_stage(scaffold=scaffold, context=context)

    assert profile_stage.path is not None
    assert profile_stage.path.exists()
    assert matching_stage.path is not None
    assert matching_stage.path.exists()
    assert verification_stage.path is not None
    assert verification_stage.path.exists()
    assert compliance_stage.path is not None
    assert compliance_stage.path.exists()
    assert anomaly_stage.path is not None
    assert anomaly_stage.path.exists()

    manifest = read_json(scaffold.artifact_manifest_path)
    metrics = read_json(scaffold.artifacts_dir / "metrics.json")
    assert manifest["artifacts"]["candidate_profile"]["status"] == "created"
    assert manifest["artifacts"]["candidate_profiles"]["status"] == "created"
    assert manifest["artifacts"]["match_scores"]["status"] == "created"
    assert manifest["artifacts"]["verification_findings"]["status"] == "created"
    assert manifest["artifacts"]["compliance_flags"]["status"] == "created"
    assert manifest["artifacts"]["anomaly_findings"]["status"] == "created"
    assert metrics["extraction"]["candidate_profile_written"] is True
    assert metrics["extraction"]["candidate_profiles_written"] is True
    assert metrics["extraction"]["artifact_paths"] == [
        "artifacts/candidate_profile.json",
        "artifacts/candidate_profiles.json",
    ]
    assert metrics["extraction"]["ocr"]["enabled"] is False
    assert metrics["extraction"]["ocr"]["attempted"] is False
    assert metrics["extraction"]["ocr"]["scan_detected"] is False
    assert metrics["extraction"]["ocr"]["scan_detected_page_count"] == 0
    assert metrics["extraction"]["ocr"]["extraction_methods"] == []
    assert metrics["extraction"]["ocr"]["provider"] is None
    assert metrics["extraction"]["ocr"]["manual_review_required"] is False
    assert "by_candidate" in metrics["extraction"]["ocr"]
    assert metrics["extraction"]["llm_recovery"]["called"] is False
    assert metrics["llm_enabled"] is False
    assert metrics["llm_provider_used"] is None
    assert metrics["llm_resume_extraction_calls"] == 0
    assert metrics["scanned_resume_detected_count"] == 0
    assert set(
        metrics["extraction"]["llm_recovery"]["final_extraction_modes"]
    ).issubset({"deterministic", "deterministic_plus_llm", "synthetic_fallback"})
    assert "manual_review_flag_count" in metrics["extraction"]["llm_recovery"]
    assert "by_candidate" in metrics["extraction"]["llm_recovery"]


def test_matching_stage_skips_without_candidate_profile(tmp_path: Path) -> None:
    scaffold, context = prepare_ready_context(tmp_path)

    result = run_matching_stage(scaffold=scaffold, context=context)

    assert result.path is None
    assert result.created_artifacts == ()
    assert result.skipped_stages == ("match_scores",)
    assert result.warnings


def test_vision_extraction_metrics_and_review_flag_are_preserved(
    tmp_path: Path,
    monkeypatch,
) -> None:
    scaffold, context = prepare_ready_context(tmp_path)
    transcription = "Jane Doe\njane.doe@example.com\nSkills\nPython, SQL, Docker, Git"
    monkeypatch.setattr(
        resume_extraction_stage,
        "extract_pdf_text",
        lambda path: PDFTextExtractionResult(
            source_path=str(path),
            status="success",
            text=transcription,
            pages=(
                ExtractedPDFPage(
                    page_number=1,
                    text=transcription,
                    extraction_method="llm_vision_ocr",
                    manual_review_required=True,
                ),
            ),
            page_count=1,
            ocr_enabled=True,
            ocr_available=True,
            ocr_status="success",
            scan_detected_pages=(1,),
            ocr_attempted_pages=(1,),
            ocr_succeeded_pages=(1,),
            ocr_provider="openai_responses_vision",
            ocr_manual_review_required=True,
        ),
    )

    result = resume_extraction_stage.run_resume_extraction_stage(
        scaffold=scaffold,
        context=context,
    )

    assert result.path is not None
    profile = read_json(scaffold.artifacts_dir / "candidate_profile.json")
    metrics = read_json(scaffold.artifacts_dir / "metrics.json")
    assert (
        "Vision-extracted resume text requires manual review."
        in profile["manual_review_flags"]
    )
    assert metrics["extraction"]["ocr"]["provider"] == "openai_responses_vision"
    assert metrics["extraction"]["ocr"]["manual_review_required"] is True
    assert metrics["extraction"]["ocr"]["scan_detected"] is True
    assert metrics["extraction"]["ocr"]["scan_detected_page_count"] == 1
    assert metrics["extraction"]["ocr"]["extraction_methods"] == [
        "llm_vision_ocr"
    ]
    assert metrics["llm_enabled"] is True
    assert metrics["llm_provider_used"] == "openai_responses_vision"
    assert metrics["llm_resume_extraction_calls"] == 1
    assert metrics["scanned_resume_detected_count"] == 1


def test_summary_metrics_count_vision_and_recovery_calls(tmp_path: Path) -> None:
    scaffold, _ = prepare_ready_context(tmp_path)

    resume_extraction_stage._update_extraction_metrics(
        scaffold=scaffold,
        llm_metrics_by_candidate={
            "candidate-1:application-1": {
                "enabled": True,
                "available": True,
                "called": True,
                "provider": "openai_chat_completions",
            }
        },
        ocr_metrics_by_candidate={
            "candidate-1:application-1": {
                "enabled": True,
                "available": True,
                "scan_detected": True,
                "scan_detected_page_count": 1,
                "attempted": True,
                "attempted_page_count": 1,
                "succeeded_page_count": 1,
                "failed_page_count": 0,
                "provider": "openai_responses_vision",
                "extraction_methods": ["llm_vision_ocr"],
            }
        },
    )

    metrics = read_json(scaffold.artifacts_dir / "metrics.json")
    assert metrics["llm_enabled"] is True
    assert metrics["llm_provider_used"] == (
        "openai_chat_completions,openai_responses_vision"
    )
    assert metrics["llm_resume_extraction_calls"] == 2
    assert metrics["scanned_resume_detected_count"] == 1


def prepare_ready_context(tmp_path: Path):
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)
    intake_result = run_application_intake(
        loaded_bundle=loaded_bundle, scaffold=scaffold
    )

    assert intake_result.ready_for_downstream
    assert loaded_bundle.context is not None

    return scaffold, loaded_bundle.context
