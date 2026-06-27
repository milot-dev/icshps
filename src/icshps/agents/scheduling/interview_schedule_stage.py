from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
from typing import Any, Protocol

from icshps.agents.scheduling.config import load_interview_schedule_config
from icshps.agents.scheduling.google_calendar_provider import (
    BusyInterval,
    GoogleCalendarFreeBusyProvider,
)
from icshps.schemas import (
    CandidateProfile,
    CandidateRoutingDecision,
    FinalDecisionArtifact,
    Finding,
    FindingCategory,
    InterviewScheduleArtifact,
    InterviewScheduleItem,
    InterviewScheduleWarning,
    RoutingCategory,
)
from icshps.services import (
    AgentStageResult,
    RunScaffold,
    artifact_path,
    read_candidate_profiles,
    read_json_artifact,
    read_reviewer_approvals,
    write_json_artifact,
)
from icshps.utils.file_io import read_json_object, write_json

ELIGIBLE_ROUTING_CATEGORIES = {
    RoutingCategory.FAST_TRACK_REVIEW,
    RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW,
}
AUDIT_SECTION_HEADING = "## Interview Schedule Suggestions"


class FreeBusyProvider(Protocol):
    def query_busy(
        self,
        *,
        panel_members: tuple[Any, ...],
        time_min: datetime,
        time_max: datetime,
        timezone_name: str,
    ) -> dict[str, list[BusyInterval]]:
        """Return busy windows by calendar ID."""


def run_interview_schedule_stage(
    *,
    scaffold: RunScaffold,
    final_decision: FinalDecisionArtifact | None = None,
    provider: FreeBusyProvider | None = None,
    now: datetime | None = None,
) -> AgentStageResult:
    """Write advisory interview schedule suggestions after final routing."""

    warnings: list[InterviewScheduleWarning] = []
    resolved_final_decision = final_decision or _read_final_decision(scaffold, warnings)
    if resolved_final_decision is None:
        artifact = _artifact(scaffold=scaffold, warnings=warnings)
        path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
        _update_metrics(scaffold=scaffold, item_count=0)
        _append_audit_log(scaffold=scaffold, artifact=artifact)
        return AgentStageResult(
            path=path,
            created_artifacts=("interview_schedule",),
            skipped_stages=("interview_schedule",),
            warnings=tuple(warning.message for warning in warnings),
        )

    eligible_decisions = _eligible_decisions(
        final_decision=resolved_final_decision,
        candidate_profiles=read_candidate_profiles(scaffold),
        warnings=warnings,
    )
    if not eligible_decisions:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_NO_ELIGIBLE_CANDIDATES",
                message="No candidates were eligible for interview scheduling.",
            )
        )
        artifact = _artifact(scaffold=scaffold, warnings=warnings)
        path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
        _update_metrics(scaffold=scaffold, item_count=0)
        _append_audit_log(scaffold=scaffold, artifact=artifact)
        return AgentStageResult(
            path=path,
            created_artifacts=("interview_schedule",),
            skipped_stages=("interview_schedule",),
            warnings=tuple(warning.message for warning in warnings),
        )

    approved_decisions = _approved_decisions(
        scaffold=scaffold,
        eligible_decisions=eligible_decisions,
        warnings=warnings,
    )
    if not approved_decisions:
        artifact = _artifact(scaffold=scaffold, warnings=warnings)
        path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
        _update_metrics(scaffold=scaffold, item_count=0)
        _append_audit_log(scaffold=scaffold, artifact=artifact)
        return AgentStageResult(
            path=path,
            created_artifacts=("interview_schedule",),
            skipped_stages=("interview_schedule",),
            warnings=tuple(warning.message for warning in warnings),
        )

    config = load_interview_schedule_config()
    warnings.extend(config.warnings)

    if not config.panel_members:
        artifact = _artifact(scaffold=scaffold, warnings=warnings)
        path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
        _update_metrics(scaffold=scaffold, item_count=0)
        _append_audit_log(scaffold=scaffold, artifact=artifact)
        return AgentStageResult(
            path=path,
            created_artifacts=("interview_schedule",),
            skipped_stages=("interview_schedule",),
            warnings=tuple(warning.message for warning in warnings),
        )

    if provider is None:
        if config.credentials_file is None or not config.credentials_file.exists():
            warnings.append(
                InterviewScheduleWarning(
                    code="GOOGLE_CALENDAR_CREDENTIALS_MISSING",
                    message=(
                        "Google Calendar credentials are not configured, so "
                        "interview schedule suggestions were not generated."
                    ),
                )
            )
            artifact = _artifact(scaffold=scaffold, warnings=warnings)
            path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
            _update_metrics(scaffold=scaffold, item_count=0)
            _append_audit_log(scaffold=scaffold, artifact=artifact)
            return AgentStageResult(
                path=path,
                created_artifacts=("interview_schedule",),
                skipped_stages=("interview_schedule",),
                warnings=tuple(warning.message for warning in warnings),
            )

        provider = GoogleCalendarFreeBusyProvider(
            credentials_file=str(config.credentials_file)
        )

    time_min, time_max = _search_bounds(
        now=now,
        timezone=config.timezone,
        search_workdays=config.search_workdays,
        workday_start=config.workday_start,
        workday_end=config.workday_end,
    )

    try:
        busy_by_calendar = provider.query_busy(
            panel_members=config.panel_members,
            time_min=time_min,
            time_max=time_max,
            timezone_name=config.timezone_name,
        )
    except Exception as exc:
        warnings.append(
            InterviewScheduleWarning(
                code="GOOGLE_CALENDAR_AVAILABILITY_UNAVAILABLE",
                message=(
                    "Google Calendar availability could not be loaded, so "
                    f"interview schedule suggestions were not generated: {exc}"
                ),
            )
        )
        artifact = _artifact(scaffold=scaffold, warnings=warnings)
        path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
        _update_metrics(scaffold=scaffold, item_count=0)
        _append_audit_log(scaffold=scaffold, artifact=artifact)
        return AgentStageResult(
            path=path,
            created_artifacts=("interview_schedule",),
            skipped_stages=("interview_schedule",),
            warnings=tuple(warning.message for warning in warnings),
        )

    items: list[InterviewScheduleItem] = []
    reserved_slots: list[BusyInterval] = []
    candidate_slots = _candidate_slots(
        now=now,
        timezone=config.timezone,
        search_workdays=config.search_workdays,
        workday_start=config.workday_start,
        workday_end=config.workday_end,
        duration_minutes=config.duration_minutes,
    )

    for decision in approved_decisions:
        slot = _first_available_slot(
            candidate_slots=candidate_slots,
            duration_minutes=config.duration_minutes,
            panel_calendar_ids=tuple(member.calendar_id for member in config.panel_members),
            busy_by_calendar=busy_by_calendar,
            reserved_slots=reserved_slots,
        )
        if slot is None:
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_NO_OVERLAPPING_SLOT",
                    message=(
                        "No overlapping panel availability was found for an "
                        "eligible candidate."
                    ),
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        slot_end = slot + timedelta(minutes=config.duration_minutes)
        reserved_slots.append(BusyInterval(start=slot, end=slot_end))
        items.append(
            InterviewScheduleItem(
                candidate_id=decision.candidate_id,
                application_id=decision.application_id,
                routing_category=decision.routing_category,
                suggested_time=slot,
                duration_minutes=config.duration_minutes,
                panel_members=list(config.panel_members),
                reason=(
                    "Candidate is eligible for interview review and all selected "
                    "panel members are available."
                ),
            )
        )

    artifact = _artifact(scaffold=scaffold, items=items, warnings=warnings)
    path = _write_schedule_artifact(scaffold=scaffold, artifact=artifact)
    _update_metrics(scaffold=scaffold, item_count=len(items))
    _append_audit_log(scaffold=scaffold, artifact=artifact)

    return AgentStageResult(
        path=path,
        created_artifacts=("interview_schedule",),
        skipped_stages=() if items else ("interview_schedule",),
        warnings=tuple(warning.message for warning in warnings),
    )


def _approved_decisions(
    *,
    scaffold: RunScaffold,
    eligible_decisions: Sequence[CandidateRoutingDecision],
    warnings: list[InterviewScheduleWarning],
) -> list[CandidateRoutingDecision]:
    approvals_result = read_reviewer_approvals(scaffold.run_dir)
    if not approvals_result.ok:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_REVIEWER_APPROVALS_UNAVAILABLE",
                message=approvals_result.errors[0],
            )
        )
        return []

    approvals_by_key = {
        (approval.candidate_id, approval.application_id): approval
        for approval in approvals_result.approvals
    }
    approved: list[CandidateRoutingDecision] = []

    for decision in eligible_decisions:
        key = (decision.candidate_id, decision.application_id)
        approval = approvals_by_key.get(key)
        if approval is None:
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_REVIEWER_APPROVAL_REQUIRED",
                    message=(
                        "Candidate is eligible for interview scheduling but has "
                        "not been approved for scheduling in the app."
                    ),
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        if approval.action == "approve_for_scheduling":
            approved.append(decision)
            continue

        if approval.action == "hold":
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_REVIEWER_APPROVAL_HELD",
                    message="Candidate scheduling is on hold after human review.",
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_REVIEWER_REJECTED_AFTER_REVIEW",
                message="Candidate was rejected after human review.",
                candidate_id=decision.candidate_id,
                application_id=decision.application_id,
            )
        )

    if eligible_decisions and not approved:
        warnings.append(
            InterviewScheduleWarning(
                code="INTERVIEW_NO_APPROVED_CANDIDATES",
                message=(
                    "No routing-eligible candidates have human approval for "
                    "interview scheduling in the app."
                ),
            )
        )

    return approved


def _read_final_decision(
    scaffold: RunScaffold,
    warnings: list[InterviewScheduleWarning],
) -> FinalDecisionArtifact | None:
    payload = read_json_artifact(scaffold=scaffold, artifact_key="final_decision")
    if payload is None:
        warnings.append(
            InterviewScheduleWarning(
                code="FINAL_ROUTING_MISSING",
                message=(
                    "Final routing output is missing, so interview schedule "
                    "suggestions were not generated."
                ),
            )
        )
        return None
    return FinalDecisionArtifact.model_validate(payload)


def _eligible_decisions(
    *,
    final_decision: FinalDecisionArtifact,
    candidate_profiles: Sequence[CandidateProfile],
    warnings: list[InterviewScheduleWarning],
) -> list[CandidateRoutingDecision]:
    profiles_with_manual_flags = {
        (profile.candidate_id, profile.application_id)
        for profile in candidate_profiles
        if profile.manual_review_flags
    }
    findings_by_key = _findings_by_candidate(final_decision.findings)
    eligible: list[CandidateRoutingDecision] = []

    for decision in sorted(
        final_decision.decisions,
        key=lambda item: (
            _route_rank(item.routing_category),
            -(item.score if item.score is not None else -1.0),
            item.candidate_id,
            item.application_id,
        ),
    ):
        key = (decision.candidate_id, decision.application_id)
        if not decision.candidate_id.strip() or not decision.application_id.strip():
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_CANDIDATE_ID_INCOMPLETE",
                    message=(
                        "Candidate was skipped because candidate_id or "
                        "application_id is incomplete."
                    ),
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        if decision.routing_category not in ELIGIBLE_ROUTING_CATEGORIES:
            continue

        if key in profiles_with_manual_flags:
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_CANDIDATE_MANUAL_REVIEW_FLAG",
                    message=(
                        "Candidate was skipped because candidate profile has "
                        "manual-review flags."
                    ),
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        candidate_findings = findings_by_key.get(key, [])
        if any(_is_disqualifying_finding(finding) for finding in candidate_findings):
            warnings.append(
                InterviewScheduleWarning(
                    code="INTERVIEW_CANDIDATE_HAS_BLOCKING_REVIEW_ISSUE",
                    message=(
                        "Candidate was skipped because compliance, credential, "
                        "fraud/anomaly, or manual-review issues exist."
                    ),
                    candidate_id=decision.candidate_id,
                    application_id=decision.application_id,
                )
            )
            continue

        eligible.append(decision)

    return eligible


def _findings_by_candidate(
    findings: Sequence[Finding],
) -> dict[tuple[str, str], list[Finding]]:
    findings_by_key: dict[tuple[str, str], list[Finding]] = {}
    for finding in findings:
        if finding.candidate_id is None or finding.application_id is None:
            continue
        findings_by_key.setdefault(
            (finding.candidate_id, finding.application_id),
            [],
        ).append(finding)
    return findings_by_key


def _is_disqualifying_finding(finding: Finding) -> bool:
    if finding.category in {
        FindingCategory.COMPLIANCE,
        FindingCategory.CREDENTIAL,
        FindingCategory.ANOMALY,
        FindingCategory.LINKEDIN_CONSISTENCY,
    }:
        return True

    text = " ".join(
        value.lower()
        for value in (
            finding.title,
            finding.description,
            finding.reason or "",
            finding.source_agent,
        )
    )
    return any(
        token in text
        for token in (
            "fraud",
            "manual review",
            "manual-review",
            "manual_review",
        )
    )


def _route_rank(category: RoutingCategory) -> int:
    if category == RoutingCategory.FAST_TRACK_REVIEW:
        return 0
    if category == RoutingCategory.ADVANCE_TO_INTERVIEW_REVIEW:
        return 1
    return 99


def _search_bounds(
    *,
    now: datetime | None,
    timezone: Any,
    search_workdays: int,
    workday_start: time,
    workday_end: time,
) -> tuple[datetime, datetime]:
    days = _workdays(now=now, timezone=timezone, count=search_workdays)
    return (
        datetime.combine(days[0], workday_start, tzinfo=timezone),
        datetime.combine(days[-1], workday_end, tzinfo=timezone),
    )


def _candidate_slots(
    *,
    now: datetime | None,
    timezone: Any,
    search_workdays: int,
    workday_start: time,
    workday_end: time,
    duration_minutes: int,
) -> list[datetime]:
    slots: list[datetime] = []
    for day in _workdays(now=now, timezone=timezone, count=search_workdays):
        cursor = datetime.combine(day, workday_start, tzinfo=timezone)
        day_end = datetime.combine(day, workday_end, tzinfo=timezone)
        while cursor + timedelta(minutes=duration_minutes) <= day_end:
            slots.append(cursor)
            cursor += timedelta(minutes=15)
    return slots


def _workdays(*, now: datetime | None, timezone: Any, count: int) -> list[Any]:
    resolved_now = now.astimezone(timezone) if now else datetime.now(timezone)
    day = resolved_now.date() + timedelta(days=1)
    days: list[Any] = []
    while len(days) < count:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _first_available_slot(
    *,
    candidate_slots: Sequence[datetime],
    duration_minutes: int,
    panel_calendar_ids: tuple[str, ...],
    busy_by_calendar: dict[str, list[BusyInterval]],
    reserved_slots: Sequence[BusyInterval],
) -> datetime | None:
    for slot in candidate_slots:
        slot_interval = BusyInterval(
            start=slot,
            end=slot + timedelta(minutes=duration_minutes),
        )
        busy_intervals = [
            interval
            for calendar_id in panel_calendar_ids
            for interval in busy_by_calendar.get(calendar_id, [])
        ]
        if any(_overlaps(slot_interval, interval) for interval in busy_intervals):
            continue
        if any(_overlaps(slot_interval, interval) for interval in reserved_slots):
            continue
        return slot
    return None


def _overlaps(left: BusyInterval, right: BusyInterval) -> bool:
    return left.start < right.end and right.start < left.end


def _artifact(
    *,
    scaffold: RunScaffold,
    items: Sequence[InterviewScheduleItem] = (),
    warnings: Sequence[InterviewScheduleWarning] = (),
) -> InterviewScheduleArtifact:
    return InterviewScheduleArtifact(
        run_id=scaffold.run_id,
        items=list(items),
        warnings=list(warnings),
    )


def _write_schedule_artifact(
    *,
    scaffold: RunScaffold,
    artifact: InterviewScheduleArtifact,
) -> Any:
    return write_json_artifact(
        scaffold=scaffold,
        artifact_key="interview_schedule",
        payload=artifact,
    )


def _update_metrics(*, scaffold: RunScaffold, item_count: int) -> None:
    metrics_path = artifact_path(scaffold, "metrics")
    payload = read_json_object(metrics_path, default_empty=True)
    artifacts_created = set(payload.get("artifacts_created") or [])
    artifacts_created.add("artifacts/interview_schedule.json")
    payload.update(
        {
            "interview_schedule_items_created": item_count,
            "artifacts_created": sorted(artifacts_created),
        }
    )
    write_json(metrics_path, payload)


def _append_audit_log(
    *,
    scaffold: RunScaffold,
    artifact: InterviewScheduleArtifact,
) -> None:
    path = artifact_path(scaffold, "audit_log")
    status = "generated" if artifact.items else "skipped"
    warning_lines = "".join(
        f"- `{warning.code}`: {warning.message}\n" for warning in artifact.warnings
    )
    if not warning_lines:
        warning_lines = "- None.\n"

    section = (
        f"{AUDIT_SECTION_HEADING}\n\n"
        f"- Status: `{status}`\n"
        f"- Schedule suggestions created: `{len(artifact.items)}`\n"
        "- Calendar source: `google_calendar`\n"
        "- Requires human confirmation: `true`\n"
        "- Calendar events created automatically: `false`\n"
        "- Emails or candidate invitations sent: `false`\n\n"
        "### Scheduling warnings\n\n"
        f"{warning_lines}"
    )
    _upsert_audit_log_section(path=path, section=section)


def _upsert_audit_log_section(*, path: Any, section: str) -> None:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    heading_start = existing.find(AUDIT_SECTION_HEADING)
    section_text = f"\n{section.strip()}\n"

    if heading_start == -1:
        path.write_text(f"{existing.rstrip()}{section_text}", encoding="utf-8")
        return

    replace_start = heading_start
    if replace_start > 0 and existing[replace_start - 1] == "\n":
        replace_start -= 1

    replace_end = existing.find("\n## ", heading_start + len(AUDIT_SECTION_HEADING))
    if replace_end == -1:
        replace_end = len(existing)

    updated = (
        existing[:replace_start].rstrip()
        + section_text
        + existing[replace_end:].lstrip("\n")
    )
    path.write_text(updated, encoding="utf-8")
