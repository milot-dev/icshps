from __future__ import annotations

import io
from pathlib import Path
import zipfile

from icshps.services.reviewer_approvals import ReviewerApproval
from icshps.utils import streamlit as streamlit_utils


def test_candidate_review_rows_join_decisions_profiles_matches_and_approvals() -> None:
    approvals = [
        ReviewerApproval(
            candidate_id="candidate_001",
            application_id="app_001",
            action="approve_for_scheduling",
            reviewer_name="Ada",
            note="Panel ready.",
            source_routing_category="Advance to interview review",
            score=96.0,
            created_at="2026-06-24T10:00:00Z",
            updated_at="2026-06-24T10:00:00Z",
        )
    ]

    rows = streamlit_utils.build_candidate_review_rows(
        final_decision={
            "decisions": [
                {
                    "candidate_id": "candidate_001",
                    "application_id": "app_001",
                    "routing_category": "Advance to interview review",
                    "score": 96.0,
                    "requires_human_approval": True,
                    "reason": "Strong match.",
                    "blocking_finding_ids": [],
                }
            ],
            "findings": [
                {
                    "candidate_id": "candidate_001",
                    "application_id": "app_001",
                    "severity": "info",
                }
            ],
        },
        profiles=[
            {
                "candidate_id": "candidate_001",
                "application_id": "app_001",
                "full_name": {"value": "Ada Candidate"},
            }
        ],
        match_results={
            "results": [
                {
                    "candidate_id": "candidate_001",
                    "application_id": "app_001",
                    "score": 96.0,
                }
            ]
        },
        approvals=approvals,
    )

    assert rows == [
        {
            "candidate_id": "candidate_001",
            "application_id": "app_001",
            "candidate_name": "Ada Candidate",
            "routing_category": "Advance to interview review",
            "score": 96.0,
            "match_score": 96.0,
            "requires_human_approval": True,
            "reason": "Strong match.",
            "blocking_finding_count": 0,
            "finding_count": 1,
            "approval_action": "approve_for_scheduling",
            "approval_label": "Approved for scheduling",
            "approval_note": "Panel ready.",
            "reviewer_name": "Ada",
            "updated_at": "2026-06-24T10:00:00Z",
        }
    ]


def test_read_candidate_profiles_payload_falls_back_to_single_profile() -> None:
    profiles = streamlit_utils.read_candidate_profiles_payload(
        {
            "candidate_profile": {
                "candidate_id": "candidate_legacy",
                "application_id": "app_legacy",
            }
        }
    )

    assert profiles == [
        {
            "candidate_id": "candidate_legacy",
            "application_id": "app_legacy",
        }
    ]


def test_approved_candidates_appear_in_calendar_queue() -> None:
    queue_rows = streamlit_utils.build_calendar_queue_rows(
        [
            {
                "candidate_name": "Ada Candidate",
                "candidate_id": "candidate_001",
                "application_id": "app_001",
                "approval_action": "approve_for_scheduling",
                "routing_category": "Advance to interview review",
                "score": 96.0,
                "reviewer_name": "Ada",
                "updated_at": "2026-06-24T10:00:00Z",
            },
            {
                "candidate_name": "Hold Candidate",
                "candidate_id": "candidate_002",
                "application_id": "app_002",
                "approval_action": "hold",
                "routing_category": "Manual review",
                "score": 70.0,
                "reviewer_name": "Ada",
                "updated_at": "2026-06-24T11:00:00Z",
            },
        ]
    )

    assert queue_rows == [
        {
            "candidate_name": "Ada Candidate",
            "candidate_id": "candidate_001",
            "application_id": "app_001",
            "status": "Ready for scheduling",
            "source_routing_category": "Advance to interview review",
            "score": 96.0,
            "reviewer_name": "Ada",
            "approval_updated_at": "2026-06-24T10:00:00Z",
        }
    ]


def test_dashboard_summary_aggregates_multiple_runs(tmp_path: Path) -> None:
    run_a = tmp_path / "runs" / "run_a"
    run_b = tmp_path / "runs" / "run_b"

    summary = streamlit_utils.build_dashboard_summary(
        [
            {
                "run_dir": run_a,
                "payloads": {
                    "metrics": {
                        "run_id": "run_a",
                        "bundle_id": "bundle_a",
                        "scenario_type": "clean",
                        "candidate_count": 2,
                        "decision_count": 2,
                        "finding_count": 1,
                        "routing_category_counts": {
                            "Advance to interview review": 1,
                            "Manual review": 1,
                        },
                        "interview_schedule_items_created": 1,
                    }
                },
                "candidate_rows": [
                    {"approval_action": "approve_for_scheduling"},
                    {"approval_action": None},
                ],
            },
            {
                "run_dir": run_b,
                "payloads": {
                    "metrics": {
                        "run_id": "run_b",
                        "bundle_id": "bundle_b",
                        "scenario_type": "surge",
                        "candidate_count": 3,
                        "decision_count": 3,
                        "finding_count": 4,
                        "routing_category_counts": {
                            "Manual review": 2,
                            "Surge processing mode": 1,
                        },
                        "fraud_findings_count": 2,
                    }
                },
                "candidate_rows": [
                    {"approval_action": "approve_for_scheduling"},
                    {"approval_action": "hold"},
                    {"approval_action": None},
                ],
            },
        ]
    )

    assert summary["run_count"] == 2
    assert summary["candidate_count"] == 5
    assert summary["decision_count"] == 5
    assert summary["finding_count"] == 5
    assert summary["approved_count"] == 2
    assert summary["metrics"]["interview_schedule_items_created"] == 1
    assert summary["metrics"]["fraud_findings_count"] == 2
    assert summary["routing_rows"] == [
        {"Routing category": "Advance to interview review", "Count": 1},
        {"Routing category": "Manual review", "Count": 3},
        {"Routing category": "Surge processing mode", "Count": 1},
    ]


def test_run_directories_only_returns_generated_run_dirs(tmp_path: Path) -> None:
    valid_run = tmp_path / "runs" / "valid_run"
    helper_dir = tmp_path / "runs" / "_uploaded_bundles"
    valid_run.mkdir(parents=True)
    helper_dir.mkdir(parents=True)
    (valid_run / "artifact_manifest.json").write_text("{}", encoding="utf-8")

    assert streamlit_utils.run_directories(tmp_path / "runs") == [valid_run]


def test_extract_uploaded_bundle_zip_returns_bundle_root(tmp_path: Path) -> None:
    archive_bytes = _zip_bytes(
        {
            "uploaded_bundle/manifest.yaml": "bundle:\n  id: uploaded_bundle\n",
            "uploaded_bundle/job_description.md": "# Role\n",
        }
    )

    bundle_path = streamlit_utils.extract_uploaded_bundle_zip(
        archive_bytes=archive_bytes,
        filename="uploaded_bundle.zip",
        upload_root=tmp_path / "uploads",
    )

    assert bundle_path.name == "uploaded_bundle"
    assert (bundle_path / "manifest.yaml").exists()
    assert (bundle_path / "job_description.md").exists()


def test_extract_uploaded_bundle_zip_rejects_unsafe_paths(tmp_path: Path) -> None:
    archive_bytes = _zip_bytes(
        {
            "../manifest.yaml": "bundle:\n  id: unsafe\n",
        }
    )

    try:
        streamlit_utils.extract_uploaded_bundle_zip(
            archive_bytes=archive_bytes,
            filename="unsafe.zip",
            upload_root=tmp_path / "uploads",
        )
    except ValueError as exc:
        assert "unsafe path" in str(exc)
    else:
        raise AssertionError("Expected unsafe ZIP path to be rejected")


def test_extract_uploaded_bundle_zip_requires_one_manifest(tmp_path: Path) -> None:
    archive_bytes = _zip_bytes(
        {
            "a/manifest.yaml": "bundle:\n  id: a\n",
            "b/manifest.yaml": "bundle:\n  id: b\n",
        }
    )

    try:
        streamlit_utils.extract_uploaded_bundle_zip(
            archive_bytes=archive_bytes,
            filename="many.zip",
            upload_root=tmp_path / "uploads",
        )
    except ValueError as exc:
        assert "exactly one manifest.yaml" in str(exc)
    else:
        raise AssertionError("Expected multi-manifest ZIP to be rejected")


def _zip_bytes(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    return buffer.getvalue()
