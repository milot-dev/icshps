from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import Field, field_validator

from icshps.schemas.common import ICSHPSBaseModel, RoutingCategory


class PanelMember(ICSHPSBaseModel):
    """One interview panel calendar used for availability lookup."""

    name: str
    email: str
    calendar_id: str


class InterviewScheduleWarning(ICSHPSBaseModel):
    """Controlled warning explaining why schedule suggestions were limited."""

    code: str
    message: str
    candidate_id: str | None = None
    application_id: str | None = None


class InterviewScheduleItem(ICSHPSBaseModel):
    """Advisory interview slot suggestion for one candidate application."""

    candidate_id: str
    application_id: str
    routing_category: Literal[
        RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
        RoutingCategory.FAST_TRACK_REVIEW,
    ]
    suggested_time: datetime
    duration_minutes: int = Field(gt=0)
    panel_members: list[PanelMember] = Field(min_length=1)
    reason: str
    calendar_source: Literal["google_calendar"] = "google_calendar"
    requires_human_confirmation: Literal[True] = True

    @field_validator("suggested_time")
    @classmethod
    def suggested_time_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("suggested_time must include timezone information")
        return value


class InterviewScheduleArtifact(ICSHPSBaseModel):
    """V2 interview schedule artifact written after final routing."""

    run_id: str
    calendar_source: Literal["google_calendar"] = "google_calendar"
    items: list[InterviewScheduleItem] = Field(default_factory=list)
    warnings: list[InterviewScheduleWarning] = Field(default_factory=list)
    requires_human_confirmation: Literal[True] = True


class InterviewScheduleEventRecord(ICSHPSBaseModel):
    """Google Calendar event created after a reviewer confirms a suggestion."""

    candidate_id: str
    application_id: str
    calendar_id: str
    event_id: str
    title: str
    start: datetime
    end: datetime
    duration_minutes: int = Field(gt=0)
    approved_by: str
    created_at: datetime
    html_link: str | None = None
    panel_members: list[PanelMember] = Field(default_factory=list)
    status: Literal["created"] = "created"


class InterviewScheduleEventsArtifact(ICSHPSBaseModel):
    """Calendar holds created from confirmed interview suggestions."""

    run_id: str
    calendar_source: Literal["google_calendar"] = "google_calendar"
    events: list[InterviewScheduleEventRecord] = Field(default_factory=list)
    warnings: list[InterviewScheduleWarning] = Field(default_factory=list)
