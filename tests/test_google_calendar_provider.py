from __future__ import annotations

from datetime import datetime, timezone

import pytest

from icshps.agents.scheduling.google_calendar_provider import (
    build_freebusy_body,
    parse_freebusy_response,
)
from icshps.schemas import PanelMember


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
