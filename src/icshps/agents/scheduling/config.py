from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import time
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from icshps.schemas import InterviewScheduleWarning, PanelMember

PANEL_MEMBERS_ENV = "ICSHPS_INTERVIEW_PANEL_MEMBERS_JSON"
GOOGLE_CREDENTIALS_FILE_ENV = "ICSHPS_GOOGLE_CALENDAR_CREDENTIALS_FILE"
GOOGLE_APPLICATION_CREDENTIALS_ENV = "GOOGLE_APPLICATION_CREDENTIALS"
TIMEZONE_ENV = "ICSHPS_INTERVIEW_TIMEZONE"
DURATION_MINUTES_ENV = "ICSHPS_INTERVIEW_DURATION_MINUTES"
SEARCH_WORKDAYS_ENV = "ICSHPS_INTERVIEW_SEARCH_WORKDAYS"
WORKDAY_START_ENV = "ICSHPS_INTERVIEW_WORKDAY_START"
WORKDAY_END_ENV = "ICSHPS_INTERVIEW_WORKDAY_END"

DEFAULT_TIMEZONE = "Europe/Belgrade"
DEFAULT_DURATION_MINUTES = 45
DEFAULT_SEARCH_WORKDAYS = 10
DEFAULT_WORKDAY_START = "10:00"
DEFAULT_WORKDAY_END = "17:00"


@dataclass(frozen=True)
class InterviewScheduleConfig:
    panel_members: tuple[PanelMember, ...]
    credentials_file: Path | None
    timezone_name: str
    timezone: ZoneInfo
    duration_minutes: int
    search_workdays: int
    workday_start: time
    workday_end: time
    warnings: tuple[InterviewScheduleWarning, ...] = ()


def load_interview_schedule_config() -> InterviewScheduleConfig:
    warnings: list[InterviewScheduleWarning] = []
    timezone_name = os.getenv(TIMEZONE_ENV, DEFAULT_TIMEZONE).strip() or DEFAULT_TIMEZONE
    timezone = _load_timezone(timezone_name, warnings)
    duration_minutes = _positive_int(
        DURATION_MINUTES_ENV,
        DEFAULT_DURATION_MINUTES,
        warnings,
    )
    search_workdays = _positive_int(
        SEARCH_WORKDAYS_ENV,
        DEFAULT_SEARCH_WORKDAYS,
        warnings,
    )
    workday_start = _parse_time(
        WORKDAY_START_ENV,
        DEFAULT_WORKDAY_START,
        warnings,
    )
    workday_end = _parse_time(
        WORKDAY_END_ENV,
        DEFAULT_WORKDAY_END,
        warnings,
    )
    if workday_end <= workday_start:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_WORKDAY_WINDOW_INVALID",
                message=(
                    "Interview workday end must be after start; using 10:00-17:00."
                ),
            )
        )
        workday_start = _time_from_text(DEFAULT_WORKDAY_START)
        workday_end = _time_from_text(DEFAULT_WORKDAY_END)

    return InterviewScheduleConfig(
        panel_members=_load_panel_members(warnings),
        credentials_file=_credentials_file(),
        timezone_name=timezone_name,
        timezone=timezone,
        duration_minutes=duration_minutes,
        search_workdays=search_workdays,
        workday_start=workday_start,
        workday_end=workday_end,
        warnings=tuple(warnings),
    )


def _load_panel_members(
    warnings: list[InterviewScheduleWarning],
) -> tuple[PanelMember, ...]:
    raw_value = os.getenv(PANEL_MEMBERS_ENV, "").strip()
    if not raw_value:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_PANEL_MEMBERS_MISSING",
                message=(
                    "Interview panel members are not configured, so schedule "
                    "suggestions were not generated."
                ),
            )
        )
        return ()

    try:
        payload = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_PANEL_MEMBERS_INVALID_JSON",
                message=f"Interview panel config is not valid JSON: {exc}",
            )
        )
        return ()

    if not isinstance(payload, list):
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_PANEL_MEMBERS_INVALID",
                message="Interview panel config must be a JSON list.",
            )
        )
        return ()

    panel_members: list[PanelMember] = []
    for index, item in enumerate(payload, start=1):
        try:
            member = PanelMember.model_validate(item)
        except Exception as exc:
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_PANEL_MEMBER_INVALID",
                    message=f"Panel member {index} is invalid: {exc}",
                )
            )
            continue
        if not member.calendar_id:
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_PANEL_CALENDAR_ID_MISSING",
                    message=f"Panel member {index} is missing calendar_id.",
                )
            )
            continue
        panel_members.append(member)

    if not panel_members:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_PANEL_MEMBERS_MISSING",
                message="No valid interview panel members were configured.",
            )
        )

    return tuple(panel_members)


def _credentials_file() -> Path | None:
    raw_value = (
        os.getenv(GOOGLE_CREDENTIALS_FILE_ENV, "").strip()
        or os.getenv(GOOGLE_APPLICATION_CREDENTIALS_ENV, "").strip()
    )
    return Path(raw_value).expanduser() if raw_value else None


def _load_timezone(
    timezone_name: str,
    warnings: list[InterviewScheduleWarning],
) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name)
    except ZoneInfoNotFoundError:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_TIMEZONE_INVALID",
                message=(
                    f"Timezone '{timezone_name}' is invalid; using "
                    f"{DEFAULT_TIMEZONE}."
                ),
            )
        )
        return ZoneInfo(DEFAULT_TIMEZONE)


def _positive_int(
    env_name: str,
    default: int,
    warnings: list[InterviewScheduleWarning],
) -> int:
    raw_value = os.getenv(env_name, "").strip()
    if not raw_value:
        return default
    try:
        value = int(raw_value)
    except ValueError:
        warnings.append(
            InterviewScheduleWarning(
                code=f"{env_name}_INVALID",
                message=f"{env_name} must be an integer; using {default}.",
            )
        )
        return default
    if value <= 0:
        warnings.append(
            InterviewScheduleWarning(
                code=f"{env_name}_INVALID",
                message=f"{env_name} must be positive; using {default}.",
            )
        )
        return default
    return value


def _parse_time(
    env_name: str,
    default: str,
    warnings: list[InterviewScheduleWarning],
) -> time:
    raw_value = os.getenv(env_name, "").strip() or default
    try:
        return _time_from_text(raw_value)
    except ValueError:
        warnings.append(
            InterviewScheduleWarning(
                code=f"{env_name}_INVALID",
                message=f"{env_name} must use HH:MM format; using {default}.",
            )
        )
        return _time_from_text(default)


def _time_from_text(value: str) -> time:
    hour_text, minute_text = value.split(":", maxsplit=1)
    return time(hour=int(hour_text), minute=int(minute_text))
