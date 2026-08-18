from __future__ import annotations

import json
from pathlib import Path

import pytest

from icshps.graph import run_langgraph_workflow
from icshps.schemas import (
    ArtifactStatus,
    FinalDecisionArtifact,
    InterviewScheduleArtifact,
    RunArtifactManifest,
)

STABLE_BUNDLE = Path("data/hiring_bundles/clean_standard_application")

REQUIRED_MVP_ARTIFACTS = (
    "inputs/context_packet.json",
    "artifacts/intake_findings.json",
    "artifacts/candidate_profile.json",
    "artifacts/candidate_profiles.json",
    "artifacts/match_scores.json",
    "artifacts/compliance_flags.md",
    "artifacts/verification_findings.json",
    "artifacts/anomaly_findings.json",
    "artifacts/final_decision.json",
    "artifacts/shortlist.csv",
    "artifacts/hiring_packet.json",
    "artifacts/metrics.json",
    "artifacts/audit_log.md",
)

OPTIONAL_V2_ARTIFACT_KEYS = (
    "interview_schedule",
    "interview_schedule_events",
    "fraud_findings",
    "ats_payload",
)

OPTIONAL_V2_ARTIFACT_PATHS = (
    "artifacts/interview_schedule.json",
    "artifacts/interview_schedule_events.json",
    "artifacts/fraud_findings.json",
    "artifacts/ats_payload.json",
)

V2_METRIC_DEFAULTS = {
    "llm_enabled": False,
    "llm_provider_used": None,
    "llm_resume_extraction_calls": 0,
    "local_llm_fallback_used": False,
    "scanned_resume_detected_count": 0,
    "interview_schedule_items_created": 0,
    "interview_schedule_events_created": 0,
    "fraud_findings_count": 0,
    "ats_mock_records_loaded": 0,
}


@pytest.fixture(autouse=True)
def deterministic_optional_feature_env(monkeypatch) -> None:
    monkeypatch.setenv("ICSHPS_LLM_EXTRACTION_ENABLED", "false")


def test_python_workflow_still_generates_required_mvp_artifacts(
    tmp_path: Path,
) -> None:
    result = run_langgraph_workflow(
        STABLE_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.ok
    assert result.run_dir is not None
    assert_required_artifacts_exist(result.run_dir)


def test_langgraph_workflow_still_generates_required_mvp_artifacts(
    tmp_path: Path,
) -> None:
    result = run_langgraph_workflow(
        STABLE_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.ok
    assert result.run_dir is not None
    assert result.artifact_manifest_path is not None
    assert_required_artifacts_exist(result.run_dir)

    final_decision = read_json(result.run_dir / "artifacts" / "final_decision.json")
    manifest = read_json(result.artifact_manifest_path)

    FinalDecisionArtifact.model_validate(final_decision)
    RunArtifactManifest.model_validate(manifest)


def test_optional_v2_artifacts_are_reserved_but_not_required(
    tmp_path: Path,
) -> None:
    result = run_langgraph_workflow(
        STABLE_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.run_dir is not None
    assert result.artifact_manifest_path is not None

    manifest = RunArtifactManifest.model_validate(read_json(result.artifact_manifest_path))

    for key in ("interview_schedule_events",):
        artifact = manifest.artifacts[key]
        assert artifact.required_for_mvp is False
        assert artifact.status == ArtifactStatus.RESERVED

    for key in ("fraud_findings", "ats_payload"):
        artifact = manifest.artifacts[key]
        assert artifact.required_for_mvp is False
        assert artifact.status == ArtifactStatus.CREATED

    interview_schedule = manifest.artifacts["interview_schedule"]
    assert interview_schedule.required_for_mvp is False
    assert interview_schedule.status == ArtifactStatus.CREATED
    assert (result.run_dir / "artifacts/interview_schedule.json").exists()

    for relative_path in (
        "artifacts/interview_schedule_events.json",
    ):
        assert not (result.run_dir / relative_path).exists(), relative_path

    for relative_path in (
        "artifacts/fraud_findings.json",
        "artifacts/ats_payload.json",
    ):
        assert (result.run_dir / relative_path).exists(), relative_path

    artifact = InterviewScheduleArtifact.model_validate(
        read_json(result.run_dir / "artifacts/interview_schedule.json")
    )
    assert artifact.items == []
    assert artifact.requires_human_confirmation is True


def test_v2_metrics_defaults_exist_after_completed_run(tmp_path: Path) -> None:
    result = run_langgraph_workflow(
        STABLE_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.run_dir is not None

    metrics = read_json(result.run_dir / "artifacts" / "metrics.json")

    for key, expected_value in V2_METRIC_DEFAULTS.items():
        assert metrics[key] == expected_value

    llm_recovery = metrics["extraction"]["llm_recovery"]
    assert metrics["extraction"]["candidate_profile_written"] is True
    assert llm_recovery["enabled"] is False
    assert llm_recovery["called"] is False
    assert "by_candidate" in llm_recovery


def test_audit_log_includes_v2_optional_feature_status(tmp_path: Path) -> None:
    result = run_langgraph_workflow(
        STABLE_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.run_dir is not None

    text = (result.run_dir / "artifacts" / "audit_log.md").read_text(encoding="utf-8")
    normalized = text.lower()

    assert "v2 optional feature status" in normalized
    assert "interview scheduling" in normalized
    assert "interview schedule suggestions" in normalized
    assert "fraud findings" in normalized
    assert "ats mock payload" in normalized
    assert "llm-assisted extraction" in normalized
    assert "real external integrations" in normalized


def assert_required_artifacts_exist(run_dir: Path) -> None:
    for relative_path in REQUIRED_MVP_ARTIFACTS:
        assert (run_dir / relative_path).exists(), relative_path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
