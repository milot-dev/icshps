from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from icshps.schemas import (
    InterviewScheduleArtifact,
    InterviewScheduleItem,
    PanelMember,
    RoutingCategory,
)


def test_interview_schedule_artifact_accepts_valid_example() -> None:
    artifact = InterviewScheduleArtifact(
        run_id="run_001",
        items=[
            InterviewScheduleItem(
                candidate_id="candidate_001",
                application_id="app_001",
                routing_category=RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
                suggested_time=datetime(2026, 7, 1, 10, 0, tzinfo=timezone.utc),
                duration_minutes=45,
                panel_members=[
                    PanelMember(
                        name="Panel Member Name",
                        email="panel@example.com",
                        calendar_id="panel@example.com",
                    )
                ],
                reason=(
                    "Candidate is eligible for interview review and all selected "
                    "panel members are available."
                ),
            )
        ],
    )

    assert artifact.items[0].calendar_source == "google_calendar"
    assert artifact.items[0].requires_human_confirmation is True
    assert artifact.requires_human_confirmation is True


def test_interview_schedule_rejects_false_human_confirmation() -> None:
    with pytest.raises(ValidationError):
        InterviewScheduleItem.model_validate(
            {
                "candidate_id": "candidate_001",
                "application_id": "app_001",
                "routing_category": "Fast-track review",
                "suggested_time": "2026-07-01T10:00:00+00:00",
                "duration_minutes": 45,
                "panel_members": [
                    {
                        "name": "Panel",
                        "email": "panel@example.com",
                        "calendar_id": "panel@example.com",
                    }
                ],
                "reason": "Available.",
                "requires_human_confirmation": False,
            }
        )


def test_interview_schedule_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        InterviewScheduleArtifact.model_validate(
            {
                "run_id": "run_001",
                "items": [],
                "warnings": [],
                "unexpected": "not allowed",
            }
        )


def test_interview_schedule_rejects_naive_suggested_time() -> None:
    with pytest.raises(ValidationError):
        InterviewScheduleItem(
            candidate_id="candidate_001",
            application_id="app_001",
            routing_category=RoutingCategory.FAST_TRACK_REVIEW,
            suggested_time=datetime(2026, 7, 1, 10, 0),
            duration_minutes=45,
            panel_members=[
                PanelMember(
                    name="Panel",
                    email="panel@example.com",
                    calendar_id="panel@example.com",
                )
            ],
            reason="Available.",
        )
