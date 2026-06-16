from __future__ import annotations

import csv
import json
from pathlib import Path

from icshps.agents.orchestrator.routing_agent import build_final_decision_artifact
from icshps.schemas import (
    ArtifactStatus,
    BundleContext,
    BundleInfo,
    CandidateApplication,
    CandidateMatchResult,
    CandidateProfile,
    ExtractedField,
    FinalDecisionArtifact,
    JobInfo,
    MatchResultsArtifact,
    OptionalInputPaths,
    RequiredInputPaths,
    RoutingCategory,
    RunArtifactManifest,
    ScenarioInfo,
)
from icshps.services import prepare_run_scaffold, write_json_artifact
from icshps.services.final_artifacts import SHORTLIST_COLUMNS, write_final_run_artifacts


def test_final_artifacts_are_written_and_final_decision_validates(
    tmp_path: Path,
) -> None:
    scaffold = scaffold_with_inputs(tmp_path)
    final_decision = final_decision_for(scaffold.run_id)

    write_final_run_artifacts(scaffold=scaffold, final_decision=final_decision)

    final_decision_path = scaffold.artifacts_dir / "final_decision.json"
    assert final_decision_path.exists()

    validated = FinalDecisionArtifact.model_validate(read_json(final_decision_path))
    assert validated.run_id == scaffold.run_id
    assert validated.decisions[0].requires_human_approval is True


def test_shortlist_csv_has_deterministic_columns_and_order(tmp_path: Path) -> None:
    scaffold = scaffold_with_inputs(tmp_path)

    final_decision = FinalDecisionArtifact(
        run_id=scaffold.run_id,
        bundle_id="bundle_001",
        scenario_type="combined",
        decisions=[
            {
                "candidate_id": "candidate_b",
                "application_id": "app_b",
                "routing_category": RoutingCategory.MANUAL_REVIEW,
                "reason": "Manual review. Human approval is required.",
                "score": 80.0,
                "blocking_finding_ids": [],
                "requires_human_approval": True,
            },
            {
                "candidate_id": "candidate_a",
                "application_id": "app_a",
                "routing_category": RoutingCategory.FAST_TRACK_REVIEW,
                "reason": "Fast-track review. Human approval is required.",
                "score": 92.0,
                "blocking_finding_ids": [],
                "requires_human_approval": True,
            },
        ],
        findings=[],
    )

    write_final_run_artifacts(scaffold=scaffold, final_decision=final_decision)

    with (scaffold.artifacts_dir / "shortlist.csv").open(
        encoding="utf-8",
        newline="",
    ) as file:
        rows = list(csv.DictReader(file))

    assert list(rows[0].keys()) == list(SHORTLIST_COLUMNS)
    assert rows[0]["candidate_id"] == "candidate_a"
    assert rows[0]["rank"] == "1"
    assert rows[0]["requires_human_approval"] == "true"


def test_hiring_packet_is_local_mock_only(tmp_path: Path) -> None:
    scaffold = scaffold_with_inputs(tmp_path)

    write_final_run_artifacts(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id),
    )

    payload = read_json(scaffold.artifacts_dir / "hiring_packet.json")

    assert payload["final_hiring_decision_made_by_system"] is False
    assert payload["requires_human_approval"] is True
    assert "Local demo-only mock payload" in payload["mock_hris_payload_note"]
    assert "does not post to a real HRIS" in payload["mock_hris_payload_note"]


def test_metrics_include_routing_counts(tmp_path: Path) -> None:
    scaffold = scaffold_with_inputs(tmp_path)

    write_final_run_artifacts(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id),
    )

    payload = read_json(scaffold.artifacts_dir / "metrics.json")

    assert payload["candidate_count"] == 1
    assert payload["finding_count"] == 1
    assert payload["blocking_finding_count"] == 1
    assert payload["routing_counts"] == {
        "Recommended rejection — human approval required": 1
    }
    assert payload["deterministic"] is True


def test_audit_log_includes_routing_summary_and_human_approval_reminder(
    tmp_path: Path,
) -> None:
    scaffold = scaffold_with_inputs(tmp_path)

    write_final_run_artifacts(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id),
    )

    text = (scaffold.artifacts_dir / "audit_log.md").read_text(encoding="utf-8")

    assert "## Candidate Routing Summary" in text
    assert "Recommended rejection — human approval required" in text
    assert "## Human Approval Reminder" in text
    assert "Every recommendation requires human approval" in text


def test_artifact_manifest_marks_final_artifacts_created(tmp_path: Path) -> None:
    scaffold = scaffold_with_inputs(tmp_path)

    write_final_run_artifacts(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id),
    )

    manifest = RunArtifactManifest.model_validate(
        read_json(scaffold.artifact_manifest_path)
    )

    for key in ("final_decision", "shortlist", "hiring_packet", "metrics", "audit_log"):
        assert manifest.artifacts[key].status == ArtifactStatus.CREATED


def test_repeated_final_artifact_writes_are_stable(tmp_path: Path) -> None:
    scaffold = scaffold_with_inputs(tmp_path)
    final_decision = final_decision_for(scaffold.run_id)

    write_final_run_artifacts(scaffold=scaffold, final_decision=final_decision)
    first = artifact_snapshot(scaffold.artifacts_dir)

    write_final_run_artifacts(scaffold=scaffold, final_decision=final_decision)
    second = artifact_snapshot(scaffold.artifacts_dir)

    assert first == second


def test_missing_optional_member_outputs_do_not_crash(tmp_path: Path) -> None:
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
        run_id="run_missing_optional",
    )

    context = context_for(scaffold.run_id)
    write_json_artifact(scaffold=scaffold, artifact_key="context_packet", payload=context)

    final_decision = build_final_decision_artifact(context=context)

    write_final_run_artifacts(scaffold=scaffold, final_decision=final_decision)

    assert (scaffold.artifacts_dir / "final_decision.json").exists()
    assert (scaffold.artifacts_dir / "shortlist.csv").exists()
    assert (scaffold.artifacts_dir / "hiring_packet.json").exists()


def scaffold_with_inputs(tmp_path: Path):
    bundle_path = build_bundle(tmp_path)
    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
        run_id="run_001",
    )

    context = context_for(scaffold.run_id)

    profile = CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        extraction_confidence=0.95,
    )

    match_results = MatchResultsArtifact(
        run_id=scaffold.run_id,
        results=[
            CandidateMatchResult(
                candidate_id="candidate_001",
                application_id="app_001",
                job_id="job_001",
                score=88.0,
                missing_mandatory_requirements=["Security+"],
            )
        ],
    )

    write_json_artifact(scaffold=scaffold, artifact_key="context_packet", payload=context)
    write_json_artifact(scaffold=scaffold, artifact_key="candidate_profile", payload=profile)
    write_json_artifact(scaffold=scaffold, artifact_key="match_scores", payload=match_results)

    return scaffold


def final_decision_for(run_id: str) -> FinalDecisionArtifact:
    context = context_for(run_id)

    return build_final_decision_artifact(
        context=context,
        match_results=MatchResultsArtifact(
            run_id=run_id,
            results=[
                CandidateMatchResult(
                    candidate_id="candidate_001",
                    application_id="app_001",
                    job_id="job_001",
                    score=88.0,
                    missing_mandatory_requirements=["Security+"],
                )
            ],
        ),
    )


def context_for(run_id: str) -> BundleContext:
    return BundleContext(
        run_id=run_id,
        bundle_path=Path("bundle"),
        bundle=BundleInfo(id="bundle_001", name="Bundle 001"),
        scenario=ScenarioInfo(id="scenario_001", type="missing_certification"),
        job=JobInfo(id="job_001", title="AI Backend Engineer"),
        candidates=[
            CandidateApplication(
                id="candidate_001",
                application_id="app_001",
                name="Sample Candidate",
                target_job_id="job_001",
                resume_file=Path("resume.pdf"),
            )
        ],
        required_inputs=RequiredInputPaths(
            job_description=Path("job_description.md"),
            skills_matrix=Path("skills_matrix.yaml"),
            eeo_policy=Path("eeo_policy.yaml"),
            credential_rules=Path("credential_rules.yaml"),
            hris_master=Path("hris_master.yaml"),
        ),
        optional_inputs=OptionalInputPaths(),
        is_ready=True,
    )


def build_bundle(tmp_path: Path) -> Path:
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text(
        "manifest_version: '1.0'\n",
        encoding="utf-8",
    )
    return bundle_path


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def artifact_snapshot(artifacts_dir: Path) -> dict[str, str]:
    names = (
        "final_decision.json",
        "shortlist.csv",
        "hiring_packet.json",
        "metrics.json",
        "audit_log.md",
    )
    return {name: (artifacts_dir / name).read_text(encoding="utf-8") for name in names}