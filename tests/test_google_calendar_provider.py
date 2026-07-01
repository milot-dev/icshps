from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace
from datetime import datetime, timezone

import pytest

from icshps.agents.scheduling.google_calendar_provider import (
    GoogleCalendarFreeBusyProvider,
    build_calendar_event_body,
    build_freebusy_body,
    parse_freebusy_response,
)
from icshps.schemas import InterviewScheduleItem, PanelMember, RoutingCategory


def test_google_freebusy_body_uses_calendar_ids_only() -> None:
    body = build_freebusy_body(
        panel_members=(
            PanelMember(
                name="Panel",
                email="panel@example.com",
                calendar_id="panel@example.com",
            ),
        ),
        time_min=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
        time_max=datetime(2026, 7, 1, 17, 0, tzinfo=timezone.utc),
        timezone_name="Europe/Budapest",
    )

    assert body == {
        "timeMin": "2026-07-01T09:00:00+00:00",
        "timeMax": "2026-07-01T17:00:00+00:00",
        "timeZone": "Europe/Budapest",
        "items": [{"id": "panel@example.com"}],
    }


def test_parse_freebusy_response_returns_busy_intervals() -> None:
    busy = parse_freebusy_response(
        {
            "calendars": {
                "panel@example.com": {
                    "busy": [
                        {
                            "start": "2026-07-01T10:00:00+00:00",
                            "end": "2026-07-01T11:00:00+00:00",
                        }
                    ]
                }
            }
        }
    )

    assert list(busy) == ["panel@example.com"]
    assert busy["panel@example.com"][0].start.isoformat() == (
        "2026-07-01T10:00:00+00:00"
    )


def test_parse_freebusy_response_raises_for_calendar_errors() -> None:
    with pytest.raises(RuntimeError, match="notFound"):
        parse_freebusy_response(
            {
                "calendars": {
                    "missing@example.com": {
                        "errors": [{"reason": "notFound"}],
                        "busy": [],
                    }
                }
            }
        )


def test_calendar_event_body_creates_hold_without_attendees() -> None:
    item = InterviewScheduleItem(
        candidate_id="candidate_001",
        application_id="app_001",
        routing_category=RoutingCategory.FAST_TRACK_REVIEW,
        suggested_time=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
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

    body = build_calendar_event_body(
        schedule_item=item,
        candidate_name="Ada Candidate",
        candidate_email="ada@example.com",
        approved_by="Rita Reviewer",
        run_id="run_001",
        timezone_name="Europe/Belgrade",
    )

    assert body["summary"] == "Interview: Ada Candidate"
    assert body["end"]["dateTime"] == "2026-07-01T09:45:00+00:00"
    assert "attendees" not in body
    assert "No automatic candidate invitation was sent." in body["description"]


def test_create_event_disables_updates_and_omits_attendees(monkeypatch) -> None:
    inserted: dict = {}

    class Request:
        def execute(self):
            return {"id": "event_001"}

    class Events:
        def insert(self, **kwargs):
            inserted.update(kwargs)
            return Request()

    class Service:
        def events(self):
            return Events()

    service_account = ModuleType("google.oauth2.service_account")
    service_account.Credentials = SimpleNamespace(
        from_service_account_file=lambda *args, **kwargs: object()
    )
    discovery = ModuleType("googleapiclient.discovery")
    discovery.build = lambda *args, **kwargs: Service()
    monkeypatch.setitem(sys.modules, "google.oauth2.service_account", service_account)
    monkeypatch.setitem(sys.modules, "googleapiclient.discovery", discovery)

    provider = GoogleCalendarFreeBusyProvider(credentials_file="credentials.json")
    provider.create_event(
        calendar_id="panel@example.com",
        schedule_item=schedule_item(),
        candidate_name="Ada Candidate",
        candidate_email="ada@example.com",
        approved_by="Rita Reviewer",
        run_id="run_001",
        timezone_name="Europe/Belgrade",
    )

    assert inserted["sendUpdates"] == "none"
    assert "attendees" not in inserted["body"]


def schedule_item() -> InterviewScheduleItem:
    return InterviewScheduleItem(
        candidate_id="candidate_001",
        application_id="app_001",
        routing_category=RoutingCategory.FAST_TRACK_REVIEW,
        suggested_time=datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc),
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
