from __future__ import annotations

import json
from pathlib import Path

import pytest

from icshps.services.reviewer_approvals import (
    approval_action_label,
    read_reviewer_approvals,
    reviewer_approvals_path,
    upsert_reviewer_approval,
)


def test_read_reviewer_approvals_returns_empty_when_missing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo_run"
    run_dir.mkdir(parents=True)

    result = read_reviewer_approvals(run_dir)

    assert result.ok
    assert result.approvals == ()
    assert result.artifact_path == reviewer_approvals_path(run_dir)


def test_upsert_reviewer_approval_creates_valid_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo_run"
    run_dir.mkdir(parents=True)

    approval = upsert_reviewer_approval(
        run_dir=run_dir,
        candidate_id="candidate_001",
        application_id="app_001",
        action="approve_for_scheduling",
        reviewer_name="Ada",
        note="Ready for panel.",
        source_routing_category="Advance to interview review",
        score=98.5,
    )

    payload = json.loads(reviewer_approvals_path(run_dir).read_text(encoding="utf-8"))

    assert approval.action == "approve_for_scheduling"
    assert payload["schema_version"] == "1.0"
    assert payload["run_id"] == "demo_run"
    assert payload["approvals"][0]["reviewer_name"] == "Ada"
    assert payload["approvals"][0]["score"] == 98.5


def test_upsert_reviewer_approval_replaces_same_candidate_application(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "demo_run"
    run_dir.mkdir(parents=True)

    first = upsert_reviewer_approval(
        run_dir=run_dir,
        candidate_id="candidate_001",
        application_id="app_001",
        action="approve_for_scheduling",
        reviewer_name="Ada",
    )
    second = upsert_reviewer_approval(
        run_dir=run_dir,
        candidate_id="candidate_001",
        application_id="app_001",
        action="hold",
        reviewer_name="Ada",
        note="Waiting for credentials.",
    )

    result = read_reviewer_approvals(run_dir)

    assert result.ok
    assert len(result.approvals) == 1
    assert result.approvals[0].action == "hold"
    assert result.approvals[0].note == "Waiting for credentials."
    assert result.approvals[0].created_at == first.created_at
    assert second.created_at == first.created_at


def test_read_reviewer_approvals_reports_malformed_artifact(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "demo_run"
    approvals_path = reviewer_approvals_path(run_dir)
    approvals_path.parent.mkdir(parents=True)
    approvals_path.write_text("{not json", encoding="utf-8")

    result = read_reviewer_approvals(run_dir)

    assert not result.ok
    assert result.approvals == ()
    assert "Invalid reviewer approvals artifact" in result.errors[0]


def test_upsert_reviewer_approval_does_not_overwrite_malformed_artifact(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "runs" / "demo_run"
    approvals_path = reviewer_approvals_path(run_dir)
    approvals_path.parent.mkdir(parents=True)
    approvals_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ValueError, match="Invalid reviewer approvals artifact"):
        upsert_reviewer_approval(
            run_dir=run_dir,
            candidate_id="candidate_001",
            application_id="app_001",
            action="hold",
            reviewer_name="Ada",
        )


def test_approval_action_label_defaults_to_not_reviewed() -> None:
    assert approval_action_label(None) == "Not reviewed"
    assert approval_action_label("approve_for_scheduling") == "Approved for scheduling"
