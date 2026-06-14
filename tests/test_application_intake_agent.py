from __future__ import annotations

import json
from pathlib import Path

from icshps.agents.intake import run_application_intake
from icshps.services.bundle_loader import load_hiring_bundle
from icshps.services.run_scaffolding import prepare_run_scaffold


def test_application_intake_writes_context_packet_and_findings(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)

    result = run_application_intake(loaded_bundle=loaded_bundle, scaffold=scaffold)

    assert result.ok
    assert result.ready_for_downstream is True
    assert result.context_packet_path == scaffold.inputs_dir / "context_packet.json"
    assert result.context_packet_path.exists()
    assert result.intake_findings_path == scaffold.artifacts_dir / "intake_findings.json"
    assert result.intake_findings_path.exists()
    assert (scaffold.inputs_dir / "manifest_snapshot.yaml").exists()

    context_packet = read_json(result.context_packet_path)
    assert context_packet["run_id"] == scaffold.run_id
    assert context_packet["bundle"]["id"] == "clean_standard_application"
    assert context_packet["is_ready"] is True

    findings = read_json(result.intake_findings_path)
    assert findings["run_id"] == scaffold.run_id
    assert findings["findings"][0]["id"] == "intake-context-summary-001"


def test_application_intake_turns_loader_errors_into_blocking_findings(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    (bundle_path / "requirements" / "skills_matrix.yaml").unlink()
    scaffold = prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)

    result = run_application_intake(loaded_bundle=loaded_bundle, scaffold=scaffold)

    assert not result.ok
    assert result.ready_for_downstream is False
    assert result.context_packet_path is not None
    assert result.context_packet_path.exists()
    assert result.blocking_finding_count == 1

    findings = read_json(result.intake_findings_path)
    blocking = [
        finding
        for finding in findings["findings"]
        if finding["severity"] == "blocking"
    ]

    assert len(blocking) == 1
    assert "required_inputs.skills_matrix" in blocking[0]["description"]

    context_packet = read_json(result.context_packet_path)
    assert context_packet["is_ready"] is False
    assert context_packet["validation_errors"]


def test_application_intake_handles_fatal_loader_failure_without_context(tmp_path: Path) -> None:
    bundle_path = tmp_path / "missing_manifest_bundle"
    bundle_path.mkdir()
    scaffold = prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)

    result = run_application_intake(loaded_bundle=loaded_bundle, scaffold=scaffold)

    assert not result.ok
    assert result.context_packet_path is None
    assert result.intake_findings_path.exists()
    assert result.blocking_finding_count == 1

    findings = read_json(result.intake_findings_path)
    assert findings["run_id"] == "unknown_run"
    assert findings["findings"][0]["severity"] == "blocking"
    assert "Missing required manifest file" in findings["findings"][0]["description"]


def test_application_intake_updates_metrics_and_artifact_manifest(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(bundle_path=bundle_path, runs_root=tmp_path / "runs")
    loaded_bundle = load_hiring_bundle(bundle_path, run_id=scaffold.run_id)

    run_application_intake(loaded_bundle=loaded_bundle, scaffold=scaffold)

    metrics = read_json(scaffold.artifacts_dir / "metrics.json")
    assert metrics["status"] == "intake_ready"
    assert metrics["candidate_count"] == 1
    assert metrics["intake"]["ready_for_downstream"] is True
    assert "inputs/context_packet.json" in metrics["artifacts_created"]
    assert "artifacts/intake_findings.json" in metrics["artifacts_created"]

    artifact_manifest = read_json(scaffold.artifact_manifest_path)
    assert artifact_manifest["artifacts"]["context_packet"]["status"] == "created"
    assert artifact_manifest["artifacts"]["intake_findings"]["status"] == "created"
    assert artifact_manifest["artifacts"]["manifest_snapshot"]["status"] == "created"


def test_application_intake_output_is_deterministic(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)

    first_scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )
    first_loaded = load_hiring_bundle(bundle_path, run_id=first_scaffold.run_id)
    first_result = run_application_intake(
        loaded_bundle=first_loaded,
        scaffold=first_scaffold,
    )
    first_context = first_result.context_packet_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    first_findings = first_result.intake_findings_path.read_text(encoding="utf-8")

    second_scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
    )
    second_loaded = load_hiring_bundle(bundle_path, run_id=second_scaffold.run_id)
    second_result = run_application_intake(
        loaded_bundle=second_loaded,
        scaffold=second_scaffold,
    )
    second_context = second_result.context_packet_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    second_findings = second_result.intake_findings_path.read_text(encoding="utf-8")

    assert first_scaffold.run_id == second_scaffold.run_id
    assert first_context == second_context
    assert first_findings == second_findings


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