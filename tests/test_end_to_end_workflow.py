from __future__ import annotations

import json
from pathlib import Path

from icshps.graph import run_end_to_end_workflow


def test_end_to_end_workflow_creates_current_backend_artifacts(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    result = run_end_to_end_workflow(bundle_path, runs_root=tmp_path / "runs")

    assert result.ok
    assert result.status == "completed"
    assert result.run_dir is not None
    assert result.run_dir.exists()

    assert result.context_packet_path is not None
    assert result.context_packet_path.exists()

    assert result.intake_findings_path is not None
    assert result.intake_findings_path.exists()

    assert result.candidate_profile_path is not None
    assert result.candidate_profile_path.exists()

    assert result.match_scores_path is not None
    assert result.match_scores_path.exists()

    assert result.compliance_flags_path is not None
    assert result.compliance_flags_path.exists()

    assert result.verification_findings_path is not None
    assert result.verification_findings_path.exists()

    assert result.anomaly_findings_path is not None
    assert result.anomaly_findings_path.exists()

    assert "candidate_profile" in result.created_artifacts
    assert "match_scores" in result.created_artifacts
    assert "compliance_flags" in result.created_artifacts
    assert "verification_findings" in result.created_artifacts
    assert "anomaly_findings" in result.created_artifacts

    assert "final_decision" in result.created_artifacts
    assert "shortlist" in result.created_artifacts
    assert "hiring_packet" in result.created_artifacts
    assert "metrics" in result.created_artifacts
    assert "audit_log" in result.created_artifacts

    assert (result.run_dir / "artifacts" / "final_decision.json").exists()
    assert (result.run_dir / "artifacts" / "shortlist.csv").exists()
    assert (result.run_dir / "artifacts" / "hiring_packet.json").exists()


def test_end_to_end_workflow_marks_artifact_manifest_correctly(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    result = run_end_to_end_workflow(bundle_path, runs_root=tmp_path / "runs")

    manifest = read_json(result.artifact_manifest_path)  # type: ignore[arg-type]
    artifacts = manifest["artifacts"]

    assert artifacts["context_packet"]["status"] == "created"
    assert artifacts["intake_findings"]["status"] == "created"
    assert artifacts["candidate_profile"]["status"] == "created"
    assert artifacts["match_scores"]["status"] == "created"
    assert artifacts["compliance_flags"]["status"] == "created"
    assert artifacts["verification_findings"]["status"] == "created"
    assert artifacts["anomaly_findings"]["status"] == "created"

    assert artifacts["final_decision"]["status"] == "created"
    assert artifacts["shortlist"]["status"] == "created"
    assert artifacts["hiring_packet"]["status"] == "created"
    assert artifacts["metrics"]["status"] == "created"
    assert artifacts["audit_log"]["status"] == "created"


def test_end_to_end_workflow_stops_safely_when_intake_is_blocked(
    tmp_path: Path,
) -> None:
    bundle_path = build_bundle(tmp_path)
    (bundle_path / "requirements" / "skills_matrix.yaml").unlink()

    result = run_end_to_end_workflow(bundle_path, runs_root=tmp_path / "runs")

    assert not result.ok
    assert result.status == "blocked"

    assert result.context_packet_path is not None
    assert result.context_packet_path.exists()

    assert result.intake_findings_path is not None
    assert result.intake_findings_path.exists()

    assert result.candidate_profile_path is None
    assert result.match_scores_path is None

    assert "candidate_profile" in result.skipped_stages
    assert "match_scores" in result.skipped_stages
    assert "verification_findings" in result.skipped_stages
    assert "anomaly_findings" in result.skipped_stages


def test_end_to_end_workflow_outputs_are_deterministic(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    first = run_end_to_end_workflow(bundle_path, runs_root=tmp_path / "runs")
    second = run_end_to_end_workflow(bundle_path, runs_root=tmp_path / "runs")

    assert first.run_id == second.run_id
    assert first.created_artifacts == second.created_artifacts
    assert first.pending_artifacts == second.pending_artifacts
    assert first.skipped_stages == second.skipped_stages
    assert first.warnings == second.warnings

    assert first.context_packet_path is not None
    assert second.context_packet_path is not None
    assert first.context_packet_path.read_text(encoding="utf-8") == (
        second.context_packet_path.read_text(encoding="utf-8")
    )

    assert first.candidate_profile_path is not None
    assert second.candidate_profile_path is not None
    assert first.candidate_profile_path.read_text(encoding="utf-8") == (
        second.candidate_profile_path.read_text(encoding="utf-8")
    )

    assert first.match_scores_path is not None
    assert second.match_scores_path is not None
    assert first.match_scores_path.read_text(encoding="utf-8") == (
        second.match_scores_path.read_text(encoding="utf-8")
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_bundle(tmp_path: Path) -> Path:
    bundle_path = tmp_path / "clean_standard_application"

    (bundle_path / "resumes").mkdir(parents=True)
    (bundle_path / "requirements").mkdir(parents=True)
    (bundle_path / "policies").mkdir(parents=True)
    (bundle_path / "mock_data").mkdir(parents=True)

    (bundle_path / "job_description.md").write_text(
        "# AI Backend Engineer\n"
        "We need Python, SQL, FastAPI, and LangGraph experience.\n",
        encoding="utf-8",
    )

    (bundle_path / "requirements" / "skills_matrix.yaml").write_text(
        """must_have:
  - Python
  - SQL
nice_to_have:
  - FastAPI
  - LangGraph
minimum_years_experience: 0
mandatory_certifications: []
""",
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

    (bundle_path / "mock_data" / "application_volume.yaml").write_text(
        "application_count: 5\n"
        "surge_threshold: 50\n"
        "bulk_application_flag: false\n",
        encoding="utf-8",
    )

    # Minimal invalid PDF bytes are okay here because the workflow should use
    # the existing synthetic fallback instead of crashing.
    (bundle_path / "resumes" / "candidate_001_resume.pdf").write_bytes(b"%PDF-1.4\n")

    (bundle_path / "manifest.yaml").write_text(
        """manifest_version: "1.0"

bundle:
  id: clean_standard_application
  name: Clean Standard Application
  description: Clean MVP bundle.

scenario:
  id: scenario_clean_standard_application
  type: clean_standard_application
  expected_routing: Fast-track review
  tags:
    - sprint_2

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
  application_volume: mock_data/application_volume.yaml

execution:
  deterministic: true
  allow_missing_optional_inputs: true
  require_human_review_for_final_decision: true

notes:
  - Test bundle for end-to-end orchestration.
""",
        encoding="utf-8",
    )

    return bundle_path