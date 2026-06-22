from __future__ import annotations

from pathlib import Path

from icshps.agents.anomaly import run_anomaly_stage
from icshps.agents.compliance import run_compliance_stage
from icshps.agents.extraction import run_resume_extraction_stage
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
    assert manifest["artifacts"]["match_scores"]["status"] == "created"
    assert manifest["artifacts"]["verification_findings"]["status"] == "created"
    assert manifest["artifacts"]["compliance_flags"]["status"] == "created"
    assert manifest["artifacts"]["anomaly_findings"]["status"] == "created"
    assert metrics["extraction"]["candidate_profile_written"] is True
    assert metrics["extraction"]["llm_recovery"]["called"] is False
    assert set(metrics["extraction"]["llm_recovery"]["final_extraction_modes"]).issubset(
        {"deterministic", "deterministic_plus_llm", "synthetic_fallback"}
    )
    assert "manual_review_flag_count" in metrics["extraction"]["llm_recovery"]
    assert "by_candidate" in metrics["extraction"]["llm_recovery"]


def test_matching_stage_skips_without_candidate_profile(tmp_path: Path) -> None:
    scaffold, context = prepare_ready_context(tmp_path)

    result = run_matching_stage(scaffold=scaffold, context=context)

    assert result.path is None
    assert result.created_artifacts == ()
    assert result.skipped_stages == ("match_scores",)
    assert result.warnings


def prepare_ready_context(tmp_path: Path):
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)
    intake_result = run_application_intake(loaded_bundle=loaded_bundle, scaffold=scaffold)

    assert intake_result.ready_for_downstream
    assert loaded_bundle.context is not None

    return scaffold, loaded_bundle.context
