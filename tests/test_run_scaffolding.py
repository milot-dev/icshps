import json
from pathlib import Path

from icshps.schemas import ArtifactStatus, RunArtifactManifest
from icshps.services.run_scaffolding import prepare_run_scaffold


def test_prepare_run_scaffold_creates_expected_structure(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    runs_root = tmp_path / "runs"

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=runs_root,
    )

    assert scaffold.run_dir.exists()
    assert scaffold.inputs_dir.exists()
    assert scaffold.artifacts_dir.exists()
    assert scaffold.logs_dir.exists()
    assert scaffold.tmp_dir.exists()

    assert (scaffold.run_dir / "run_metadata.json").exists()
    assert (scaffold.run_dir / "artifact_manifest.json").exists()
    assert (scaffold.artifacts_dir / "audit_log.md").exists()
    assert (scaffold.artifacts_dir / "metrics.json").exists()
    assert (scaffold.logs_dir / "audit_events.jsonl").exists()


def test_prepare_run_scaffold_uses_stable_run_id(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    runs_root = tmp_path / "runs"

    first = prepare_run_scaffold(bundle_path=bundle_path, runs_root=runs_root)
    second = prepare_run_scaffold(bundle_path=bundle_path, runs_root=runs_root)

    assert first.run_id == second.run_id


def test_downstream_artifacts_are_reserved_but_not_falsely_created(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert not (scaffold.artifacts_dir / "candidate_profile.json").exists()
    assert not (scaffold.artifacts_dir / "candidate_profiles.json").exists()
    assert not (scaffold.artifacts_dir / "match_scores.json").exists()
    assert not (scaffold.artifacts_dir / "compliance_flags.md").exists()
    assert not (scaffold.artifacts_dir / "interview_schedule.json").exists()
    assert not (scaffold.artifacts_dir / "interview_schedule_events.json").exists()
    assert not (scaffold.artifacts_dir / "fraud_findings.json").exists()
    assert not (scaffold.artifacts_dir / "ats_payload.json").exists()


def test_manifest_includes_optional_v2_artifacts(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )

    manifest = RunArtifactManifest.model_validate(
        json.loads(scaffold.artifact_manifest_path.read_text(encoding="utf-8"))
    )

    for key in (
        "interview_schedule",
        "interview_schedule_events",
        "fraud_findings",
        "ats_payload",
    ):
        artifact = manifest.artifacts[key]
        assert artifact.required_for_mvp is False
        assert artifact.status == ArtifactStatus.RESERVED


def test_initial_metrics_include_v2_defaults(tmp_path: Path) -> None:
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )

    metrics = json.loads(
        (scaffold.artifacts_dir / "metrics.json").read_text(encoding="utf-8")
    )

    assert metrics["llm_enabled"] is False
    assert metrics["llm_provider_used"] is None
    assert metrics["llm_resume_extraction_calls"] == 0
    assert metrics["local_llm_fallback_used"] is False
    assert metrics["scanned_resume_detected_count"] == 0
    assert metrics["interview_schedule_items_created"] == 0
    assert metrics["interview_schedule_events_created"] == 0
    assert metrics["fraud_findings_count"] == 0
    assert metrics["ats_mock_records_loaded"] == 0
