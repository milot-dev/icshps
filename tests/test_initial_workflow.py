from __future__ import annotations

import json
from pathlib import Path

from icshps.graph import run_initial_workflow


def test_initial_workflow_runs_completed_foundations_in_order(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    result = run_initial_workflow(
        bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert result.ok
    assert result.status == "ready_for_downstream"
    assert result.ready_for_downstream is True
    assert result.run_id is not None
    assert result.run_dir is not None
    assert result.context_packet_path is not None
    assert result.context_packet_path.exists()
    assert result.intake_findings_path is not None
    assert result.intake_findings_path.exists()
    assert result.artifact_manifest_path is not None
    assert result.artifact_manifest_path.exists()
    assert result.metrics_path is not None
    assert result.metrics_path.exists()
    assert result.audit_log_path is not None
    assert result.audit_log_path.exists()
    assert result.next_step == "Pass inputs/context_packet.json to the Resume Extraction Agent."

    assert "context_packet" in result.created_artifacts
    assert "intake_findings" in result.created_artifacts
    assert "candidate_profile" in result.pending_artifacts
    assert "match_scores" in result.pending_artifacts
    assert "compliance_flags" in result.pending_artifacts

    assert not (result.run_dir / "artifacts" / "candidate_profile.json").exists()
    assert not (result.run_dir / "artifacts" / "match_scores.json").exists()
    assert not (result.run_dir / "artifacts" / "compliance_flags.md").exists()

    audit_log = result.audit_log_path.read_text(encoding="utf-8")
    assert "Task 7: Initial Workflow Skeleton" in audit_log
    assert "prepare_run_scaffold" in audit_log
    assert "load_hiring_bundle" in audit_log
    assert "run_application_intake" in audit_log

    metadata = read_json(result.run_dir / "run_metadata.json")
    assert metadata["status"] == "completed"

    audit_events = (result.run_dir / "logs" / "audit_events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "initial_workflow_completed" in audit_events


def test_initial_workflow_stops_safely_when_intake_is_blocked(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    (bundle_path / "requirements" / "skills_matrix.yaml").unlink()

    result = run_initial_workflow(
        bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert not result.ok
    assert result.status == "blocked"
    assert result.ready_for_downstream is False
    assert result.errors
    assert any("required_inputs.skills_matrix" in error for error in result.errors)
    assert result.context_packet_path is not None
    assert result.context_packet_path.exists()
    assert result.intake_findings_path is not None
    assert result.intake_findings_path.exists()
    assert result.next_step == "Fix intake findings before running downstream agents."

    context_packet = read_json(result.context_packet_path)
    assert context_packet["is_ready"] is False
    assert context_packet["validation_errors"]

    findings = read_json(result.intake_findings_path)
    blocking = [finding for finding in findings["findings"] if finding["severity"] == "blocking"]
    assert len(blocking) == 1


def test_initial_workflow_handles_missing_manifest_as_blocked_intake(
    tmp_path: Path,
) -> None:
    bundle_path = tmp_path / "missing_manifest_bundle"
    bundle_path.mkdir()

    result = run_initial_workflow(
        bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert not result.ok
    assert result.status == "blocked"
    assert result.ready_for_downstream is False
    assert result.context_packet_path is None
    assert result.intake_findings_path is not None
    assert result.intake_findings_path.exists()
    assert result.errors
    assert "Missing required manifest file" in result.errors[0]

    findings = read_json(result.intake_findings_path)
    assert findings["findings"][0]["severity"] == "blocking"


def test_initial_workflow_missing_bundle_returns_controlled_failure(tmp_path: Path) -> None:
    missing_bundle_path = tmp_path / "does_not_exist"

    result = run_initial_workflow(
        missing_bundle_path,
        runs_root=tmp_path / "runs",
    )

    assert not result.ok
    assert result.status == "failed"
    assert result.run_id is None
    assert result.run_dir is None
    assert result.errors
    assert "Hiring Bundle path does not exist" in result.errors[0]


def test_initial_workflow_outputs_are_deterministic(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    first = run_initial_workflow(bundle_path, runs_root=tmp_path / "runs")
    first_context = first.context_packet_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    first_findings = first.intake_findings_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    first_events = (first.run_dir / "logs" / "audit_events.jsonl").read_text(  # type: ignore[operator]
        encoding="utf-8"
    )

    second = run_initial_workflow(bundle_path, runs_root=tmp_path / "runs")
    second_context = second.context_packet_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    second_findings = second.intake_findings_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    second_events = (second.run_dir / "logs" / "audit_events.jsonl").read_text(  # type: ignore[operator]
        encoding="utf-8"
    )

    assert first.run_id == second.run_id
    assert first_context == second_context
    assert first_findings == second_findings
    assert first_events == second_events


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def build_bundle(tmp_path: Path) -> Path:
    bundle_path = tmp_path / "clean_standard_application"
    (bundle_path / "resumes").mkdir(parents=True)
    (bundle_path / "requirements").mkdir(parents=True)
    (bundle_path / "policies").mkdir(parents=True)
    (bundle_path / "mock_data").mkdir(parents=True)

    (bundle_path / "job_description.md").write_text(
        "# AI Backend Engineer\n",
        encoding="utf-8",
    )
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
  linkedin_profiles: null
  application_history: null
  credential_evidence: null
  application_volume: null

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
