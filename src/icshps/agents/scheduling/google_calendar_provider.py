from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from icshps.schemas import InterviewScheduleItem, PanelMember

GOOGLE_CALENDAR_FREEBUSY_SCOPE = "https://www.googleapis.com/auth/calendar.freebusy"
GOOGLE_CALENDAR_EVENTS_SCOPE = "https://www.googleapis.com/auth/calendar"


@dataclass(frozen=True)
class BusyInterval:
    start: datetime
    end: datetime


class GoogleCalendarFreeBusyProvider:
    """Google Calendar provider for availability and confirmed calendar holds."""

    def __init__(self, *, credentials_file: str) -> None:
        self.credentials_file = credentials_file

    def query_busy(
        self,
        *,
        panel_members: tuple[PanelMember, ...],
        time_min: datetime,
        time_max: datetime,
        timezone_name: str,
    ) -> dict[str, list[BusyInterval]]:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Calendar client libraries are not installed."
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file,
            scopes=[GOOGLE_CALENDAR_FREEBUSY_SCOPE],
        )
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        response = (
            service.freebusy()
            .query(
                body=build_freebusy_body(
                    panel_members=panel_members,
                    time_min=time_min,
                    time_max=time_max,
                    timezone_name=timezone_name,
                )
            )
            .execute()
        )
        return parse_freebusy_response(response)

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
    ) -> dict[str, Any]:
        try:
            from google.oauth2 import service_account
            from googleapiclient.discovery import build
        except ImportError as exc:
            raise RuntimeError(
                "Google Calendar client libraries are not installed."
            ) from exc

        credentials = service_account.Credentials.from_service_account_file(
            self.credentials_file,
            scopes=[GOOGLE_CALENDAR_EVENTS_SCOPE],
        )
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        return (
            service.events()
            .insert(
                calendarId=calendar_id,
                body=build_calendar_event_body(
                    schedule_item=schedule_item,
                    candidate_name=candidate_name,
                    candidate_email=candidate_email,
                    approved_by=approved_by,
                    run_id=run_id,
                    timezone_name=timezone_name,
                ),
                sendUpdates="none",
            )
            .execute()
        )


def build_freebusy_body(
    *,
    panel_members: tuple[PanelMember, ...],
    time_min: datetime,
    time_max: datetime,
    timezone_name: str,
) -> dict[str, Any]:
    return {
        "timeMin": time_min.isoformat(),
        "timeMax": time_max.isoformat(),
        "timeZone": timezone_name,
        "items": [{"id": member.calendar_id} for member in panel_members],
    }


def build_calendar_event_body(
    *,
    schedule_item: InterviewScheduleItem,
    candidate_name: str,
    candidate_email: str | None,
    approved_by: str,
    run_id: str,
    timezone_name: str,
) -> dict[str, Any]:
    start = schedule_item.suggested_time
    end = start + timedelta(minutes=schedule_item.duration_minutes)
    panel = ", ".join(member.name for member in schedule_item.panel_members)
    return {
        "summary": f"Interview: {candidate_name}",
        "description": "\n".join(
            [
                f"Candidate: {candidate_name}",
                f"Candidate email: {candidate_email or 'Not provided'}",
                f"Panel: {panel or 'To be confirmed'}",
                f"Confirmed by: {approved_by}",
                f"ICSHPS run: {run_id}",
                "No automatic candidate invitation was sent.",
            ]
        ),
        "start": {"dateTime": start.isoformat(), "timeZone": timezone_name},
        "end": {"dateTime": end.isoformat(), "timeZone": timezone_name},
        "guestsCanInviteOthers": False,
        "guestsCanModify": False,
    }


def parse_freebusy_response(response: dict[str, Any]) -> dict[str, list[BusyInterval]]:
    calendar_payloads = response.get("calendars") or {}
    busy_by_calendar: dict[str, list[BusyInterval]] = {}
    errors: list[str] = []

    for calendar_id, payload in sorted(calendar_payloads.items()):
        for error in payload.get("errors") or []:
            reason = error.get("reason") or "unknown"
            errors.append(f"{calendar_id}: {reason}")

        intervals = [
            BusyInterval(
                start=datetime.fromisoformat(item["start"]),
                end=datetime.fromisoformat(item["end"]),
            )
            for item in payload.get("busy") or []
        ]
        busy_by_calendar[calendar_id] = intervals

    if errors:
        raise RuntimeError(f"Google Calendar FreeBusy returned errors: {errors}")

    return busy_by_calendar
