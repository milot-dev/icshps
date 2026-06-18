from __future__ import annotations

from pathlib import Path

from icshps.services.bundle_loader import (
    load_hiring_bundle,
    snapshot_manifest_to_run,
)
from icshps.services.run_scaffolding import prepare_run_scaffold


def test_load_hiring_bundle_returns_ready_context(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    result = load_hiring_bundle(bundle_path, run_id="run_test")

    assert result.ok
    assert result.context is not None
    assert result.context.is_ready is True
    assert result.context.run_id == "run_test"
    assert result.context.bundle.id == "clean_standard_application"
    assert result.context.candidates[0].resume_file.is_absolute()
    assert result.context.required_inputs.job_description.is_absolute()
    assert result.context.validation_errors == []


def test_load_hiring_bundle_reports_missing_manifest(tmp_path: Path) -> None:
    bundle_path = tmp_path / "missing_manifest_bundle"
    bundle_path.mkdir()

    result = load_hiring_bundle(bundle_path, run_id="run_test")

    assert not result.ok
    assert result.context is None
    assert "Missing required manifest file" in result.errors[0]


def test_load_hiring_bundle_reports_missing_required_input(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    (bundle_path / "requirements" / "skills_matrix.yaml").unlink()

    result = load_hiring_bundle(bundle_path, run_id="run_test")

    assert not result.ok
    assert result.context is not None
    assert result.context.is_ready is False
    assert any("required_inputs.skills_matrix" in error for error in result.errors)


def test_load_hiring_bundle_reports_missing_candidate_resume(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    (bundle_path / "resumes" / "candidate_001_resume.pdf").unlink()

    result = load_hiring_bundle(bundle_path, run_id="run_test")

    assert not result.ok
    assert result.context is not None
    assert result.context.is_ready is False
    assert any("resume_file" in error for error in result.errors)


def test_load_hiring_bundle_warns_for_missing_optional_input(tmp_path: Path) -> None:
    bundle_path = build_bundle(
        tmp_path,
        optional_inputs="""
  linkedin_profiles: mock_data/linkedin_profiles.yaml
  application_history: null
  credential_evidence: null
  application_volume: null
""",
    )

    result = load_hiring_bundle(bundle_path, run_id="run_test")

    assert result.context is not None
    assert result.context.is_ready is True
    assert result.errors == ()
    assert any("optional_inputs.linkedin_profiles" in warning for warning in result.warnings)


def test_snapshot_manifest_to_run_copies_manifest(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")

    snapshot_path = snapshot_manifest_to_run(bundle_path, scaffold)

    assert snapshot_path == scaffold.inputs_dir / "manifest_snapshot.yaml"
    assert snapshot_path.exists()
    snapshot_text = snapshot_path.read_text(encoding="utf-8")
    manifest_text = (bundle_path / "manifest.yaml").read_text(encoding="utf-8")

    assert snapshot_text == manifest_text


def build_bundle(
    tmp_path: Path,
    *,
    optional_inputs: str | None = None,
) -> Path:
    bundle_path = tmp_path / "clean_standard_application"
    (bundle_path / "resumes").mkdir(parents=True)
    (bundle_path / "requirements").mkdir(parents=True)
    (bundle_path / "policies").mkdir(parents=True)
    (bundle_path / "mock_data").mkdir(parents=True)

    (bundle_path / "job_description.md").write_text("# AI Backend Engineer\n", encoding="utf-8")
    (bundle_path / "requirements" / "skills_matrix.yaml").write_text(
        "must_have: []\n",
        encoding="utf-8",
    )
    (bundle_path / "policies" / "eeo_policy.yaml").write_text(
        "rules: []\n",
        encoding="utf-8",
    )
    (bundle_path / "policies" / "credential_rules.yaml").write_text(
        "rules: []\n",
        encoding="utf-8",
    )
    (bundle_path / "mock_data" / "hris_master.yaml").write_text(
        "fields: []\n",
        encoding="utf-8",
    )
    (bundle_path / "resumes" / "candidate_001_resume.pdf").write_bytes(b"%PDF-1.4\n")

    optional_inputs_block = optional_inputs or """
  linkedin_profiles: null
  application_history: null
  credential_evidence: null
  application_volume: null
"""

    (bundle_path / "manifest.yaml").write_text(
        f"""manifest_version: "1.0"

bundle:
  id: clean_standard_application
  name: Clean Standard Application
  description: Clean MVP bundle.

scenario:
  id: scenario_clean_standard_application
  type: clean_standard_application
  expected_routing: Fast-track review
  tags:
    - sprint_1

job:
  id: job_ai_backend_engineer_001
  title: AI Backend Engineer
  department: Engineering
  location: Local Demo
  employment_type: Full-time

candidates:
  - id: candidate_001
    application_id: app_001
    name: Sample Candidate
    target_job_id: job_ai_backend_engineer_001
    resume_file: resumes/candidate_001_resume.pdf

required_inputs:
  job_description: job_description.md
  skills_matrix: requirements/skills_matrix.yaml
  eeo_policy: policies/eeo_policy.yaml
  credential_rules: policies/credential_rules.yaml
  hris_master: mock_data/hris_master.yaml

optional_inputs:
{optional_inputs_block}
execution:
  deterministic: true
  allow_missing_optional_inputs: true
  require_human_review_for_final_decision: true

notes:
  - Test bundle.
""",
        encoding="utf-8",
    )

    return bundle_path
