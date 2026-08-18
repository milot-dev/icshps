from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from icshps.agents.scheduling.interview_event_stage import (
    approve_and_create_interview_event,
)
from icshps.schemas import (
    ArtifactStatus,
    InterviewScheduleArtifact,
    InterviewScheduleEventsArtifact,
    InterviewScheduleItem,
    PanelMember,
    RoutingCategory,
)
from icshps.services import prepare_run_scaffold
from icshps.utils.file_io import write_json


class FakeCalendarEventProvider:
    def __init__(self) -> None:
        self.calls = []

    def create_event(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "id": "event_001",
            "summary": "Interview: candidate_001",
            "htmlLink": "https://calendar.example/events/event_001",
        }


def test_confirmed_suggestion_creates_calendar_event(tmp_path: Path) -> None:
    scaffold = scaffold_with_schedule(tmp_path)
    provider = FakeCalendarEventProvider()

    result = approve_and_create_interview_event(
        scaffold=scaffold,
        candidate_id="candidate_001",
        application_id="app_001",
        approved_by="Ada Reviewer",
        provider=provider,
        now=datetime(2026, 7, 1, 8, 30, tzinfo=ZoneInfo("Europe/Belgrade")),
    )

    assert result.ok
    assert result.event is not None
    assert result.event.event_id == "event_001"
    assert provider.calls[0]["calendar_id"] == "panel@example.com"
    artifact = InterviewScheduleEventsArtifact.model_validate(
        json.loads(result.path.read_text(encoding="utf-8"))
    )
    assert len(artifact.events) == 1
    metrics = json.loads(
        (scaffold.artifacts_dir / "metrics.json").read_text(encoding="utf-8")
    )
    assert metrics["interview_schedule_events_created"] == 1
    manifest = json.loads(scaffold.artifact_manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["artifacts"]["interview_schedule_events"]["status"]
        == ArtifactStatus.CREATED
    )


def test_existing_event_is_not_created_twice(tmp_path: Path) -> None:
    scaffold = scaffold_with_schedule(tmp_path)
    provider = FakeCalendarEventProvider()

    for _ in range(2):
        result = approve_and_create_interview_event(
            scaffold=scaffold,
            candidate_id="candidate_001",
            application_id="app_001",
            approved_by="Ada Reviewer",
            provider=provider,
        )

    assert result.event is not None
    assert len(provider.calls) == 1


def test_event_creation_requires_reviewer_name(tmp_path: Path) -> None:
    scaffold = scaffold_with_schedule(tmp_path)
    provider = FakeCalendarEventProvider()

    result = approve_and_create_interview_event(
        scaffold=scaffold,
        candidate_id="candidate_001",
        application_id="app_001",
        approved_by="",
        provider=provider,
    )

    assert result.event is None
    assert provider.calls == []
    assert result.warnings == (
        "Enter a reviewer name before creating a calendar event.",
    )


def scaffold_with_schedule(tmp_path: Path):
    bundle_path = tmp_path / "bundle"
    bundle_path.mkdir()
    (bundle_path / "manifest.yaml").write_text("manifest_version: '1.0'\n")
    scaffold = prepare_run_scaffold(
        bundle_path=bundle_path,
        runs_root=tmp_path / "runs",
        run_id="run_001",
    )
    write_json(
        scaffold.artifacts_dir / "interview_schedule.json",
        InterviewScheduleArtifact(
            run_id=scaffold.run_id,
            items=[
                InterviewScheduleItem(
                    candidate_id="candidate_001",
                    application_id="app_001",
                    routing_category=RoutingCategory.FAST_TRACK_REVIEW,
                    suggested_time=datetime(
                        2026,
                        7,
                        1,
                        9,
                        0,
                        tzinfo=ZoneInfo("Europe/Belgrade"),
                    ),
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
            ],
        ),
    )
    return scaffold
