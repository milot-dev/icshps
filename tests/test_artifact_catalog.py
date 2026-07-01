from __future__ import annotations

import json
from pathlib import Path

from icshps.services.artifact_catalog import read_artifact_catalog
from icshps.services.run_scaffolding import prepare_run_scaffold


def test_artifact_catalog_returns_all_expected_artifacts(tmp_path: Path) -> None:
    scaffold = build_scaffold(tmp_path)

    result = read_artifact_catalog(scaffold.run_dir)

    assert result.ok
    assert result.run_id == scaffold.run_id
    assert [artifact.key for artifact in result.artifacts] == sorted(
        [
            "anomaly_findings",
            "artifact_manifest",
            "ats_payload",
            "audit_events",
            "audit_log",
            "candidate_profile",
            "candidate_profiles",
            "compliance_flags",
            "context_packet",
            "fraud_findings",
            "final_decision",
            "hiring_packet",
            "intake_findings",
            "interview_schedule",
            "interview_schedule_events",
            "manifest_snapshot",
            "match_scores",
            "metrics",
            "run_metadata",
            "shortlist",
            "verification_findings",
        ]
    )


def test_artifact_catalog_marks_existing_artifacts_available(tmp_path: Path) -> None:
    scaffold = build_scaffold(tmp_path)

    result = read_artifact_catalog(scaffold.run_dir)
    by_key = {artifact.key: artifact for artifact in result.artifacts}

    assert by_key["run_metadata"].status == "available"
    assert by_key["artifact_manifest"].status == "available"
    assert by_key["audit_log"].status == "available"
    assert by_key["metrics"].status == "available"
    assert by_key["audit_events"].status == "available"


def test_artifact_catalog_marks_missing_artifacts_not_generated_yet(tmp_path: Path) -> None:
    scaffold = build_scaffold(tmp_path)

    result = read_artifact_catalog(scaffold.run_dir)
    by_key = {artifact.key: artifact for artifact in result.artifacts}

    assert by_key["candidate_profile"].status == "not_generated_yet"
    assert by_key["candidate_profiles"].status == "not_generated_yet"
    assert by_key["match_scores"].status == "not_generated_yet"
    assert by_key["compliance_flags"].status == "not_generated_yet"
    assert by_key["shortlist"].status == "not_generated_yet"


def test_artifact_catalog_handles_optional_artifacts(tmp_path: Path) -> None:
    scaffold = build_scaffold(tmp_path)

    result = read_artifact_catalog(scaffold.run_dir)
    by_key = {artifact.key: artifact for artifact in result.artifacts}

    for key in (
        "interview_schedule",
        "interview_schedule_events",
        "fraud_findings",
        "ats_payload",
    ):
        assert by_key[key].required_for_mvp is False
        assert by_key[key].status == "not_generated_yet"


def test_artifact_catalog_uses_deterministic_order(tmp_path: Path) -> None:
    scaffold = build_scaffold(tmp_path)

    first = read_artifact_catalog(scaffold.run_dir)
    second = read_artifact_catalog(scaffold.run_dir)

    assert [artifact.as_dict() for artifact in first.artifacts] == [
        artifact.as_dict() for artifact in second.artifacts
    ]
    assert [artifact.key for artifact in first.artifacts] == sorted(
        artifact.key for artifact in first.artifacts
    )


def test_artifact_catalog_reports_missing_run_directory(tmp_path: Path) -> None:
    result = read_artifact_catalog(tmp_path / "missing_run")

    assert not result.ok
    assert result.status == "missing_run_directory"
    assert result.artifacts == ()
    assert "Run directory does not exist" in result.errors[0]


def test_artifact_catalog_reports_missing_manifest(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "run_without_manifest"
    run_dir.mkdir(parents=True)

    result = read_artifact_catalog(run_dir)

    assert not result.ok
    assert result.status == "missing_manifest"
    assert result.artifacts == ()
    assert "Missing artifact manifest" in result.errors[0]


def test_artifact_catalog_normalizes_windows_manifest_paths(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "windows_manifest_run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifacts" / "audit_log.md").write_text("# Audit\n", encoding="utf-8")
    (run_dir / "artifact_manifest.json").write_text(
        json.dumps(
            {
                "run_id": "windows_manifest_run",
                "artifacts": {
                    "audit_log": {
                        "path": "artifacts\\audit_log.md",
                        "owner": "Member 1",
                        "description": "Audit log.",
                        "status": "created",
                        "required_for_mvp": True,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    result = read_artifact_catalog(run_dir)

    assert result.ok
    assert result.artifacts[0].relative_path.as_posix() == "artifacts/audit_log.md"
    assert result.artifacts[0].status == "available"


def build_scaffold(tmp_path: Path):
    bundle_path = tmp_path / "clean_standard_application"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "bundle:\n  id: clean_standard_application\n",
        encoding="utf-8",
    )

    return prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
