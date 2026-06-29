from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icshps.agents.scheduling.google_calendar_provider import BusyInterval
from icshps.agents.scheduling.interview_schedule_stage import (
    run_interview_schedule_stage,
)
from icshps.schemas import (
    ArtifactStatus,
    BundleContext,
    BundleInfo,
    CandidateApplication,
    CandidateProfile,
    ExtractedField,
    FinalDecisionArtifact,
    Finding,
    FindingCategory,
    InterviewScheduleArtifact,
    JobInfo,
    OptionalInputPaths,
    RequiredInputPaths,
    RoutingCategory,
    RunArtifactManifest,
    ScenarioInfo,
    Severity,
)
from icshps.services import (
    prepare_run_scaffold,
    reviewer_approvals_path,
    upsert_reviewer_approval,
    write_json_artifact,
)


class FakeFreeBusyProvider:
    def __init__(self, busy_by_calendar=None):
        self.busy_by_calendar = busy_by_calendar or {}
        self.calls = []

    def query_busy(self, **kwargs):
        self.calls.append(kwargs)
        return self.busy_by_calendar


def test_fast_track_candidate_gets_schedule_suggestion(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold)
    final_decision = final_decision_for(
        scaffold.run_id,
        RoutingCategory.FAST_TRACK_REVIEW,
    )

    result = run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert result.path == scaffold.artifacts_dir / "interview_schedule.json"
    assert len(artifact.items) == 1
    assert artifact.items[0].candidate_id == "candidate_001"
    assert artifact.items[0].requires_human_confirmation is True
    assert artifact.items[0].suggested_time.isoformat() == "2026-07-01T10:00:00+02:00"


def test_advance_candidate_gets_schedule_suggestion(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold)
    final_decision = final_decision_for(
        scaffold.run_id,
        RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
    )

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert len(artifact.items) == 1
    assert artifact.items[0].routing_category == RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW


def test_candidate_requires_app_approval_before_schedule_lookup(
    tmp_path,
    monkeypatch,
) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    monkeypatch.delenv("ICSHPS_GOOGLE_CALENDAR_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    provider = FakeFreeBusyProvider()

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=provider,
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert provider.calls == []
    warning_codes = {warning.code for warning in artifact.warnings}
    assert "INTERVIEW_REVIEWER_APPROVAL_REQUIRED" in warning_codes
    assert "INTERVIEW_NO_APPROVED_CANDIDATES" in warning_codes
    assert "GOOGLE_CALENDAR_CREDENTIALS_MISSING" not in warning_codes


def test_held_candidate_is_not_scheduled(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold, action="hold")
    provider = FakeFreeBusyProvider()

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=provider,
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert provider.calls == []
    assert "INTERVIEW_REVIEWER_APPROVAL_HELD" in {
        warning.code for warning in artifact.warnings
    }


def test_rejected_candidate_is_not_scheduled(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold, action="reject_after_human_review")
    provider = FakeFreeBusyProvider()

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=provider,
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert provider.calls == []
    assert "INTERVIEW_REVIEWER_REJECTED_AFTER_REVIEW" in {
        warning.code for warning in artifact.warnings
    }


def test_malformed_approval_artifact_skips_scheduling(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approvals_path = reviewer_approvals_path(scaffold.run_dir)
    approvals_path.parent.mkdir(parents=True, exist_ok=True)
    approvals_path.write_text("{not json", encoding="utf-8")
    provider = FakeFreeBusyProvider()

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=provider,
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert provider.calls == []
    assert "INTERVIEW_REVIEWER_APPROVALS_UNAVAILABLE" in {
        warning.code for warning in artifact.warnings
    }


def test_candidates_with_review_issues_are_skipped(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    final_decision = final_decision_for(
        scaffold.run_id,
        RoutingCategory.FAST_TRACK_REVIEW,
        findings=[
            Finding(
                id="compliance-001",
                source_agent="eeo",
                category=FindingCategory.COMPLIANCE,
                severity=Severity.WARNING,
                title="Compliance issue",
                description="Needs review.",
                candidate_id="candidate_001",
                application_id="app_001",
            )
        ],
    )

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert {warning.code for warning in artifact.warnings} >= {
        "INTERVIEW_CANDIDATE_HAS_BLOCKING_REVIEW_ISSUE",
        "INTERVIEW_NO_ELIGIBLE_CANDIDATES",
    }


def test_candidate_profile_manual_review_flags_are_skipped(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    profile = CandidateProfile(
        candidate_id="candidate_001",
        application_id="app_001",
        role_id="job_001",
        source_file="resume.pdf",
        full_name=ExtractedField(value="Sample Candidate", confidence=1.0),
        extraction_confidence=0.95,
        manual_review_flags=["Check extracted name."],
    )
    write_json_artifact(
        scaffold=scaffold,
        artifact_key="candidate_profiles",
        payload=[profile.model_dump(mode="json")],
    )

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert "INTERVIEW_CANDIDATE_MANUAL_REVIEW_FLAG" in {
        warning.code for warning in artifact.warnings
    }


def test_missing_credentials_writes_warning_without_crashing(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold)
    monkeypatch.delenv("ICSHPS_GOOGLE_CALENDAR_CREDENTIALS_FILE", raising=False)
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert "GOOGLE_CALENDAR_CREDENTIALS_MISSING" in {
        warning.code for warning in artifact.warnings
    }


def test_missing_panel_config_writes_warning_without_crashing(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    approve_for_scheduling(scaffold)
    monkeypatch.delenv("ICSHPS_INTERVIEW_PANEL_MEMBERS_JSON", raising=False)

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert "INTERVIEW_PANEL_MEMBERS_MISSING" in {
        warning.code for warning in artifact.warnings
    }


def test_no_valid_slots_writes_warning(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold)
    busy_by_calendar = {
        "panel@example.com": [
            BusyInterval(
                start=datetime(2026, 7, 1, 0, 0, tzinfo=ZoneInfo("Europe/Belgrade")),
                end=datetime(2026, 7, 15, 23, 59, tzinfo=ZoneInfo("Europe/Belgrade")),
            )
        ]
    }

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=FakeFreeBusyProvider(busy_by_calendar),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert "INTERVIEW_NO_OVERLAPPING_SLOT" in {
        warning.code for warning in artifact.warnings
    }


def test_missing_final_decision_writes_warning(tmp_path, monkeypatch) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)

    run_interview_schedule_stage(
        scaffold=scaffold,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    artifact = read_schedule(scaffold)
    assert artifact.items == []
    assert "FINAL_ROUTING_MISSING" in {warning.code for warning in artifact.warnings}


def test_schedule_stage_updates_metrics_manifest_and_audit_log(
    tmp_path,
    monkeypatch,
) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    approve_for_scheduling(scaffold)

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision_for(scaffold.run_id, RoutingCategory.FAST_TRACK_REVIEW),
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    metrics = read_json(scaffold.artifacts_dir / "metrics.json")
    manifest = RunArtifactManifest.model_validate(read_json(scaffold.artifact_manifest_path))
    audit_log = (scaffold.artifacts_dir / "audit_log.md").read_text(encoding="utf-8")

    assert metrics["interview_schedule_items_created"] == 1
    assert "artifacts/interview_schedule.json" in metrics["artifacts_created"]
    assert manifest.artifacts["interview_schedule"].status == ArtifactStatus.CREATED
    assert "## Interview Schedule Suggestions" in audit_log
    assert "Calendar events created automatically: `false`" in audit_log


def test_schedule_stage_replaces_existing_audit_log_section(
    tmp_path,
    monkeypatch,
) -> None:
    scaffold = scaffold_with_context(tmp_path)
    configure_panel(monkeypatch)
    final_decision = final_decision_for(
        scaffold.run_id,
        RoutingCategory.FAST_TRACK_REVIEW,
    )

    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )
    approve_for_scheduling(scaffold)
    run_interview_schedule_stage(
        scaffold=scaffold,
        final_decision=final_decision,
        provider=FakeFreeBusyProvider(),
        now=fixed_now(),
    )

    audit_log = (scaffold.artifacts_dir / "audit_log.md").read_text(encoding="utf-8")
    assert audit_log.count("## Interview Schedule Suggestions") == 1
    assert "Status: `generated`" in audit_log
    assert "INTERVIEW_REVIEWER_APPROVAL_REQUIRED" not in audit_log


def scaffold_with_context(tmp_path: Path):
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text("manifest_version: '1.0'\n")
    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
        run_id="run_001",
    )
    write_json_artifact(
        scaffold=scaffold,
        artifact_key="context_packet",
        payload=context_for(scaffold.run_id),
    )
    return scaffold


def context_for(run_id: str) -> BundleContext:
    return BundleContext(
        run_id=run_id,
        bundle_path=Path("bundle"),
        bundle=BundleInfo(id="bundle_001", name="Bundle 001"),
        scenario=ScenarioInfo(id="scenario_001", type="clean_standard"),
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


def final_decision_for(
    run_id: str,
    routing_category: RoutingCategory,
    findings=None,
) -> FinalDecisionArtifact:
    return FinalDecisionArtifact(
        run_id=run_id,
        bundle_id="bundle_001",
        scenario_type="clean_standard",
        decisions=[
            {
                "candidate_id": "candidate_001",
                "application_id": "app_001",
                "routing_category": routing_category,
                "reason": "Human approval is required.",
                "score": 92.0,
                "blocking_finding_ids": [],
                "requires_human_approval": True,
            }
        ],
        findings=findings or [],
    )


def fixed_now() -> datetime:
    return datetime(2026, 6, 30, 12, 0, tzinfo=ZoneInfo("Europe/Belgrade"))


def configure_panel(monkeypatch) -> None:
    monkeypatch.setenv(
        "ICSHPS_INTERVIEW_PANEL_MEMBERS_JSON",
        json.dumps(
            [
                {
                    "name": "Panel",
                    "email": "panel@example.com",
                    "calendar_id": "panel@example.com",
                }
            ]
        ),
    )


def approve_for_scheduling(scaffold, action="approve_for_scheduling") -> None:
    upsert_reviewer_approval(
        run_dir=scaffold.run_dir,
        candidate_id="candidate_001",
        application_id="app_001",
        action=action,
        reviewer_name="Ada",
        source_routing_category="Fast-track review",
        score=92.0,
    )


def read_schedule(scaffold) -> InterviewScheduleArtifact:
    return InterviewScheduleArtifact.model_validate(
        read_json(scaffold.artifacts_dir / "interview_schedule.json")
    )


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
