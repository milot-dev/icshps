from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from icshps.agents.scheduling.config import load_interview_schedule_config
from icshps.agents.scheduling.google_calendar_provider import (
    GoogleCalendarFreeBusyProvider,
)
from icshps.schemas import (
    CandidateProfile,
    InterviewScheduleArtifact,
    InterviewScheduleEventRecord,
    InterviewScheduleEventsArtifact,
    InterviewScheduleItem,
    InterviewScheduleWarning,
)
from icshps.services import (
    RunScaffold,
    read_candidate_profiles,
    write_json_artifact,
)
from icshps.utils.file_io import read_json_object, write_json

EVENTS_ARTIFACT_FILENAME = "interview_schedule_events.json"


class CalendarEventProvider(Protocol):
    def create_event(
        self,
        *,
        calendar_id: str,
        schedule_item: InterviewScheduleItem,
        candidate_name: str,
        candidate_email: str | None,
        approved_by: str,
        run_id: str,
        timezone_name: str,
    ) -> dict[str, Any]: ...


@dataclass(frozen=True)
class InterviewScheduleEventResult:
    path: Path
    artifact: InterviewScheduleEventsArtifact
    event: InterviewScheduleEventRecord | None
    warnings: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.event is not None and not self.warnings


def approve_and_create_interview_event(
    *,
    scaffold: RunScaffold,
    candidate_id: str,
    application_id: str,
    approved_by: str,
    provider: CalendarEventProvider | None = None,
    now: datetime | None = None,
) -> InterviewScheduleEventResult:
    path = scaffold.artifacts_dir / EVENTS_ARTIFACT_FILENAME
    artifact = _read_events_artifact(path=path, run_id=scaffold.run_id)
    reviewer = approved_by.strip()

    if not reviewer:
        return _failure(
            path=path,
            artifact=artifact,
            warning=InterviewScheduleWarning(
                code="INTERVIEW_EVENT_APPROVER_REQUIRED",
                message="Enter a reviewer name before creating a calendar event.",
                candidate_id=candidate_id,
                application_id=application_id,
            ),
        )

    existing = _existing_event(
        artifact=artifact,
        candidate_id=candidate_id,
        application_id=application_id,
    )
    if existing is not None:
        return InterviewScheduleEventResult(path=path, artifact=artifact, event=existing)

    schedule_item = _schedule_item(
        scaffold=scaffold,
        candidate_id=candidate_id,
        application_id=application_id,
    )
    if schedule_item is None:
        return _failure(
            path=path,
            artifact=artifact,
            warning=InterviewScheduleWarning(
                code="INTERVIEW_SCHEDULE_ITEM_MISSING",
                message="Generate a schedule suggestion before creating an event.",
                candidate_id=candidate_id,
                application_id=application_id,
            ),
        )

    config = load_interview_schedule_config()
    calendar_id = schedule_item.panel_members[0].calendar_id
    if provider is None:
        if config.credentials_file is None or not config.credentials_file.exists():
            return _failure(
                path=path,
                artifact=artifact,
                warning=InterviewScheduleWarning(
                    code="GOOGLE_CALENDAR_CREDENTIALS_MISSING",
                    message=(
                        "Google Calendar credentials are not configured, so the "
                        "confirmed event was not created."
                    ),
                    candidate_id=candidate_id,
                    application_id=application_id,
                ),
            )
        active_provider: CalendarEventProvider = GoogleCalendarFreeBusyProvider(
            credentials_file=str(config.credentials_file)
        )
    else:
        active_provider = provider
    profile = _candidate_profile(
        profiles=read_candidate_profiles(scaffold),
        candidate_id=candidate_id,
        application_id=application_id,
    )
    candidate_name = _candidate_name(profile, candidate_id)
    candidate_email = _candidate_email(profile)

    try:
        response = active_provider.create_event(
            calendar_id=calendar_id,
            schedule_item=schedule_item,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            approved_by=reviewer,
            run_id=scaffold.run_id,
            timezone_name=config.timezone_name,
        )
    except Exception as exc:
        return _failure(
            path=path,
            artifact=artifact,
            warning=InterviewScheduleWarning(
                code="GOOGLE_CALENDAR_EVENT_CREATE_FAILED",
                message=f"Google Calendar event creation failed: {exc}",
                candidate_id=candidate_id,
                application_id=application_id,
            ),
        )

    event = InterviewScheduleEventRecord(
        candidate_id=candidate_id,
        application_id=application_id,
        calendar_id=calendar_id,
        event_id=str(response.get("id") or ""),
        title=str(response.get("summary") or f"Interview: {candidate_name}"),
        start=schedule_item.suggested_time,
        end=schedule_item.suggested_time
        + timedelta(minutes=schedule_item.duration_minutes),
        duration_minutes=schedule_item.duration_minutes,
        approved_by=reviewer,
        created_at=now or datetime.now(config.timezone),
        html_link=response.get("htmlLink"),
        panel_members=list(schedule_item.panel_members),
    )
    artifact = artifact.model_copy(
        update={
            "events": [*artifact.events, event],
            "warnings": [
                warning
                for warning in artifact.warnings
                if (warning.candidate_id, warning.application_id)
                != (candidate_id, application_id)
            ],
        }
    )
    try:
        path = write_json_artifact(
            scaffold=scaffold,
            artifact_key="interview_schedule_events",
            payload=artifact,
        )
    except KeyError:
        # Runs created before this optional artifact was registered remain usable.
        write_json(path, artifact)
    _update_metrics(scaffold=scaffold, event_count=len(artifact.events))
    _append_audit_log(scaffold=scaffold, event=event)
    return InterviewScheduleEventResult(path=path, artifact=artifact, event=event)


def _read_events_artifact(
    *, path: Path, run_id: str
) -> InterviewScheduleEventsArtifact:
    if not path.exists():
        return InterviewScheduleEventsArtifact(run_id=run_id)
    return InterviewScheduleEventsArtifact.model_validate(read_json_object(path))


def _schedule_item(
    *, scaffold: RunScaffold, candidate_id: str, application_id: str
) -> InterviewScheduleItem | None:
    path = scaffold.artifacts_dir / "interview_schedule.json"
    if not path.exists():
        return None
    artifact = InterviewScheduleArtifact.model_validate(read_json_object(path))
    return next(
        (
            item
            for item in artifact.items
            if (item.candidate_id, item.application_id)
            == (candidate_id, application_id)
        ),
        None,
    )


def _existing_event(
    *,
    artifact: InterviewScheduleEventsArtifact,
    candidate_id: str,
    application_id: str,
) -> InterviewScheduleEventRecord | None:
    return next(
        (
            event
            for event in artifact.events
            if (event.candidate_id, event.application_id)
            == (candidate_id, application_id)
        ),
        None,
    )


def _candidate_profile(
    *,
    profiles: list[CandidateProfile],
    candidate_id: str,
    application_id: str,
) -> CandidateProfile | None:
    return next(
        (
            profile
            for profile in profiles
            if (profile.candidate_id, profile.application_id)
            == (candidate_id, application_id)
        ),
        None,
    )


def _candidate_name(profile: CandidateProfile | None, candidate_id: str) -> str:
    if profile is not None and profile.full_name.value:
        return profile.full_name.value
    return candidate_id


def _candidate_email(profile: CandidateProfile | None) -> str | None:
    return profile.email.value if profile is not None and profile.email else None


def _failure(
    *,
    path: Path,
    artifact: InterviewScheduleEventsArtifact,
    warning: InterviewScheduleWarning,
) -> InterviewScheduleEventResult:
    updated = artifact.model_copy(update={"warnings": [*artifact.warnings, warning]})
    write_json(path, updated)
    return InterviewScheduleEventResult(
        path=path,
        artifact=updated,
        event=None,
        warnings=(warning.message,),
    )


def _update_metrics(*, scaffold: RunScaffold, event_count: int) -> None:
    path = scaffold.artifacts_dir / "metrics.json"
    payload = read_json_object(path, default_empty=True)
    artifacts_created = set(payload.get("artifacts_created") or [])
    artifacts_created.add(f"artifacts/{EVENTS_ARTIFACT_FILENAME}")
    payload["interview_schedule_events_created"] = event_count
    payload["artifacts_created"] = sorted(artifacts_created)
    write_json(path, payload)


def _append_audit_log(
    *, scaffold: RunScaffold, event: InterviewScheduleEventRecord
) -> None:
    path = scaffold.artifacts_dir / "audit_log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    section = (
        "\n## Interview Schedule Event Created\n\n"
        f"- Candidate ID: `{event.candidate_id}`\n"
        f"- Application ID: `{event.application_id}`\n"
        f"- Calendar ID: `{event.calendar_id}`\n"
        f"- Event ID: `{event.event_id}`\n"
        f"- Confirmed by: `{event.approved_by}`\n"
        f"- Starts at: `{event.start.isoformat()}`\n"
        "- Calendar updates sent: `none`\n"
    )
    path.write_text(f"{existing.rstrip()}{section}", encoding="utf-8")
