from __future__ import annotations

from pathlib import Path

from icshps.graph import run_end_to_end_workflow, run_langgraph_workflow

V2_DEMO_BUNDLE = Path("data/hiring_bundles/v2_stretch_demo")

REQUIRED_FIXTURE_FILES = (
    "manifest.yaml",
    "job_description.md",
    "requirements/skills_matrix.yaml",
    "policies/eeo_policy.yaml",
    "policies/credential_rules.yaml",
    "mock_data/hris_master.yaml",
)

FUTURE_MOCK_FILES = (
    "mock_data/panel_availability.yaml",
    "mock_data/ats_export.json",
    "mock_data/ats_requisition.json",
    "mock_data/future_fraud_signals.json",
)

REQUIRED_OUTPUTS = (
    "artifact_manifest.json",
    "artifacts/metrics.json",
    "artifacts/audit_log.md",
)

OPTIONAL_V2_ARTIFACTS = (
    "artifacts/interview_schedule.json",
    "artifacts/fraud_findings.json",
    "artifacts/ats_payload.json",
)


def test_v2_demo_fixture_has_required_bundle_structure() -> None:
    for relative_path in REQUIRED_FIXTURE_FILES:
        assert (V2_DEMO_BUNDLE / relative_path).exists(), relative_path


def test_v2_demo_fixture_runs_through_python_workflow(tmp_path: Path) -> None:
    result = run_end_to_end_workflow(
        V2_DEMO_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.ok
    assert result.run_dir is not None

    for relative_path in REQUIRED_OUTPUTS:
        assert (result.run_dir / relative_path).exists(), relative_path


def test_v2_demo_fixture_runs_through_langgraph_workflow(tmp_path: Path) -> None:
    result = run_langgraph_workflow(
        V2_DEMO_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.ok
    assert result.run_dir is not None

    for relative_path in REQUIRED_OUTPUTS:
        assert (result.run_dir / relative_path).exists(), relative_path


def test_v2_demo_fixture_future_mock_files_do_not_create_fake_artifacts(
    tmp_path: Path,
) -> None:
    for relative_path in FUTURE_MOCK_FILES:
        assert (V2_DEMO_BUNDLE / relative_path).exists(), relative_path

    result = run_end_to_end_workflow(
        V2_DEMO_BUNDLE,
        runs_root=tmp_path / "runs",
    )

    assert result.status == "completed"
    assert result.run_dir is not None

    for relative_path in OPTIONAL_V2_ARTIFACTS:
        assert not (result.run_dir / relative_path).exists(), relative_path
