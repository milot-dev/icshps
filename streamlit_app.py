from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st

from icshps.agents.scheduling import run_interview_schedule_stage
from icshps.graph import run_langgraph_workflow
from icshps.services import RunScaffold
from icshps.services.artifact_catalog import ArtifactCatalogItem, read_artifact_catalog
from icshps.services.reviewer_approvals import (
    ReviewerAction,
    read_reviewer_approvals,
    upsert_reviewer_approval,
)
from icshps.utils.streamlit import (
    artifact_kind as _artifact_kind,
    build_calendar_queue_rows,
    build_candidate_review_rows,
    build_dashboard_summary,
    bundle_directories as _bundle_directories,
    candidate_findings as _candidate_findings,
    candidate_key as _candidate_key,
    display_artifacts as _display_artifacts,
    extract_uploaded_bundle_zip,
    inject_styles as _inject_styles,
    load_display_payloads as _load_display_payloads,
    match_lookup as _match_lookup,
    profile_lookup as _profile_lookup,
    read_candidate_profiles_payload,
    render_csv as _render_csv,
    render_json as _render_json,
    render_markdown as _render_markdown,
    render_text as _render_text,
    run_directories as _run_directories,
    schedule_payload_has_items,
    yes_no as _yes_no,
)

RUNS_ROOT = Path("runs")
BUNDLES_ROOT = Path("data") / "hiring_bundles"
KOSOVO_TIMEZONE = ZoneInfo("Europe/Belgrade")
UPLOAD_ROOT = RUNS_ROOT / "_uploaded_bundles"

DISPLAY_ARTIFACT_KEYS: tuple[str, ...] = (
    "context_packet",
    "intake_findings",
    "candidate_profile",
    "candidate_profiles",
    "match_scores",
    "compliance_flags",
    "verification_findings",
    "anomaly_findings",
    "final_decision",
    "shortlist",
    "hiring_packet",
    "interview_schedule",
    "fraud_findings",
    "ats_payload",
    "metrics",
    "audit_log",
)

APPROVAL_OPTIONS: dict[str, ReviewerAction] = {
    "Approve for scheduling": "approve_for_scheduling",
    "Hold": "hold",
    "Reject after human review": "reject_after_human_review",
}
SCHEDULE_GENERATION_NOTICE_KEY = "schedule_generation_notice"


def main() -> None:
    st.set_page_config(page_title="ICSHPS Review Workspace", layout="wide")
    _inject_styles()

    st.title("ICSHPS Review Workspace")
    st.caption(
        "Human-reviewed candidate screening, approvals, and scheduling readiness."
    )

    reviewer_name = st.sidebar.text_input("Reviewer name", value="")
    selected_run = _sidebar_run_selector(RUNS_ROOT)
    _render_current_run_summary(selected_run)

    tabs = st.tabs(
        [
            "Run Intake",
            "Dashboard",
            "Candidate Review",
            "Approvals",
            "Calendar Queue",
            "Artifacts",
        ]
    )

    with tabs[0]:
        selected_run = _render_run_intake(selected_run)

    run_state = _load_run_state(selected_run)

    with tabs[1]:
        _render_dashboard(run_state)

    with tabs[2]:
        _render_candidate_review(run_state)

    with tabs[3]:
        _render_approvals(run_state, reviewer_name=reviewer_name)

    with tabs[4]:
        _render_calendar_queue(run_state)

    with tabs[5]:
        _render_artifacts(run_state)


def _sidebar_run_selector(runs_root: Path) -> Path | None:
    run_dirs = _run_directories(runs_root)
    if not run_dirs:
        st.sidebar.info("No run folders found yet.")
        return None

    run_names = [run_dir.name for run_dir in run_dirs]
    selected_name = st.session_state.get("selected_run_name")
    index = run_names.index(selected_name) if selected_name in run_names else 0

    selected = st.sidebar.selectbox("Selected run", options=run_names, index=index)
    st.session_state["selected_run_name"] = selected
    return next(run_dir for run_dir in run_dirs if run_dir.name == selected)


def _render_run_intake(selected_run: Path | None) -> Path | None:
    st.subheader("Run Intake")
    st.caption("Start from a scenario bundle, upload a bundle ZIP, or run every local scenario.")

    bundle_dirs = _bundle_directories(BUNDLES_ROOT)
    bundle_labels = [bundle.name for bundle in bundle_dirs]

    single_tab, upload_tab, batch_tab = st.tabs(
        ["Single Bundle", "Upload Bundle", "All Scenarios"]
    )

    with single_tab:
        selected_run = _render_single_bundle_runner(
            selected_run=selected_run,
            bundle_dirs=bundle_dirs,
            bundle_labels=bundle_labels,
        )

    with upload_tab:
        selected_run = _render_uploaded_bundle_runner(selected_run)

    with batch_tab:
        selected_run = _render_all_scenarios_runner(
            selected_run=selected_run,
            bundle_dirs=bundle_dirs,
        )

    return selected_run


def _render_single_bundle_runner(
    *,
    selected_run: Path | None,
    bundle_dirs: list[Path],
    bundle_labels: list[str],
) -> Path | None:
    selected_label = st.selectbox(
        "Scenario bundle",
        options=bundle_labels,
        index=0 if bundle_labels else None,
        placeholder="No bundles found",
    )
    custom_path = st.text_input(
        "Custom bundle folder",
        value="",
        placeholder="Optional: D:\\path\\to\\hiring_bundle",
    )
    reset = st.checkbox(
        "Reset existing deterministic run",
        value=True,
        key="single_bundle_reset",
    )

    if st.button("Run selected bundle", type="primary", use_container_width=True):
        bundle_path = Path(custom_path.strip()) if custom_path.strip() else None
        if bundle_path is None and selected_label:
            bundle_path = next(bundle for bundle in bundle_dirs if bundle.name == selected_label)

        if bundle_path is None:
            st.error("Choose a bundle before running the pipeline.")
            return selected_run

        new_run = _run_one_bundle(bundle_path=bundle_path, reset=reset)
        selected_run = new_run or selected_run

    return selected_run


def _render_uploaded_bundle_runner(selected_run: Path | None) -> Path | None:
    st.markdown("Upload a `.zip` containing one Hiring Bundle with a `manifest.yaml`.")
    uploaded_bundle = st.file_uploader(
        "Bundle ZIP",
        type=("zip",),
        accept_multiple_files=False,
    )
    reset = st.checkbox(
        "Reset run after upload",
        value=True,
        key="uploaded_bundle_reset",
    )

    if st.button("Upload and run bundle", type="primary", use_container_width=True):
        if uploaded_bundle is None:
            st.error("Choose a bundle ZIP first.")
            return selected_run

        try:
            bundle_path = extract_uploaded_bundle_zip(
                archive_bytes=uploaded_bundle.getvalue(),
                filename=uploaded_bundle.name,
                upload_root=UPLOAD_ROOT,
            )
        except ValueError as exc:
            st.error(str(exc))
            return selected_run

        st.success(f"Uploaded bundle: {bundle_path.name}")
        new_run = _run_one_bundle(bundle_path=bundle_path, reset=reset)
        selected_run = new_run or selected_run

    return selected_run


def _render_all_scenarios_runner(
    *,
    selected_run: Path | None,
    bundle_dirs: list[Path],
) -> Path | None:
    st.markdown("Run every scenario bundle in `data/hiring_bundles`.")
    reset = st.checkbox(
        "Reset existing deterministic runs",
        value=True,
        key="all_scenarios_reset",
    )

    if not bundle_dirs:
        st.info("No scenario bundles were found.")
        return selected_run

    st.caption(f"{len(bundle_dirs)} scenario bundle(s) ready.")

    if st.button("Run all scenarios", type="primary", use_container_width=True):
        progress = st.progress(0)
        status = st.empty()
        results: list[dict[str, str]] = []

        for index, bundle_path in enumerate(bundle_dirs, start=1):
            status.write(f"Running {bundle_path.name} ({index}/{len(bundle_dirs)})")
            result_row = _run_bundle_for_batch(bundle_path=bundle_path, reset=reset)
            results.append(result_row)
            if result_row["status"] == "completed":
                selected_run = RUNS_ROOT / result_row["run_id"]
                st.session_state["selected_run_name"] = result_row["run_id"]
            progress.progress(index / len(bundle_dirs))

        st.session_state["last_batch_results"] = results
        status.write("Batch run complete.")

    batch_results = st.session_state.get("last_batch_results")
    if batch_results:
        st.dataframe(pd.DataFrame(batch_results), use_container_width=True, hide_index=True)

    return selected_run


def _render_current_run_summary(selected_run: Path | None) -> None:
    st.markdown("##### Active Review Run")
    if selected_run is None:
        st.info("Run a bundle or select an existing run from the sidebar.")
        return

    cols = st.columns([1.2, 2])
    cols[0].metric("Run", selected_run.name)


def _run_one_bundle(*, bundle_path: Path, reset: bool) -> Path | None:
    with st.spinner(f"Running {bundle_path.name}..."):
        result_row = _run_bundle_for_batch(bundle_path=bundle_path, reset=reset)

    if result_row["status"] == "completed":
        st.session_state["selected_run_name"] = result_row["run_id"]
        st.success(f"Run completed: {result_row['run_id']}")
        return RUNS_ROOT / result_row["run_id"]

    st.error(f"Pipeline run failed: {result_row['message']}")
    return None


def _run_bundle_for_batch(*, bundle_path: Path, reset: bool) -> dict[str, str]:
    try:
        result = run_langgraph_workflow(
            bundle_path=bundle_path,
            runs_root=RUNS_ROOT,
            reset=reset,
        )
    except Exception as exc:
        return {
            "bundle": bundle_path.name,
            "status": "failed",
            "run_id": "",
            "message": str(exc),
        }

    if result.ok and result.run_dir is not None:
        return {
            "bundle": bundle_path.name,
            "status": "completed",
            "run_id": result.run_dir.name,
            "message": "ok",
        }

    return {
        "bundle": bundle_path.name,
        "status": "failed",
        "run_id": "",
        "message": result.error or result.status,
    }


def _load_run_state(selected_run: Path | None) -> dict[str, Any]:
    if selected_run is None:
        return {
            "run_dir": None,
            "catalog": None,
            "payloads": {},
            "approvals_result": None,
            "candidate_rows": [],
        }

    catalog = read_artifact_catalog(selected_run)
    payloads = _load_display_payloads(
        catalog.artifacts if catalog.ok else (),
        display_artifact_keys=DISPLAY_ARTIFACT_KEYS,
    )
    approvals_result = read_reviewer_approvals(selected_run)
    candidate_rows = build_candidate_review_rows(
        final_decision=payloads.get("final_decision"),
        profiles=read_candidate_profiles_payload(payloads),
        match_results=payloads.get("match_scores"),
        approvals=list(approvals_result.approvals),
    )

    return {
        "run_dir": selected_run,
        "catalog": catalog,
        "payloads": payloads,
        "approvals_result": approvals_result,
        "candidate_rows": candidate_rows,
    }


def _render_dashboard(run_state: dict[str, Any]) -> None:
    st.subheader("Run Dashboard")
    scope = st.radio(
        "Dashboard scope",
        options=("Selected run", "All generated runs"),
        horizontal=True,
    )

    if scope == "All generated runs":
        _render_all_runs_dashboard()
    else:
        _render_selected_run_dashboard(run_state)


def _render_selected_run_dashboard(run_state: dict[str, Any]) -> None:
    run_dir = run_state["run_dir"]
    if run_dir is None:
        st.info("No run selected yet.")
        return

    payloads = run_state["payloads"]
    metrics = payloads.get("metrics") or {}
    approvals_result = run_state["approvals_result"]
    rows = run_state["candidate_rows"]
    approved_count = sum(
        1 for row in rows if row["approval_action"] == "approve_for_scheduling"
    )

    cols = st.columns(5)
    cols[0].metric("Candidates", metrics.get("candidate_count", len(rows)))
    cols[1].metric("Decisions", metrics.get("decision_count", len(rows)))
    cols[2].metric("Findings", metrics.get("finding_count", 0))
    cols[3].metric("Approved", approved_count)
    cols[4].metric("Schedule Items", metrics.get("interview_schedule_items_created", 0))

    st.markdown("#### Routing")
    routing_counts = metrics.get("routing_category_counts") or metrics.get("routing_counts")
    if routing_counts:
        st.dataframe(
            pd.DataFrame(
                [
                    {"Routing category": key, "Count": value}
                    for key, value in routing_counts.items()
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Routing metrics are not available for this run.")

    st.markdown("#### Extraction and Future Readiness")
    extraction = metrics.get("extraction", {})
    llm_recovery = extraction.get("llm_recovery", {})
    readiness_cols = st.columns(4)
    readiness_cols[0].metric("LLM enabled", _yes_no(metrics.get("llm_enabled", False)))
    readiness_cols[1].metric("LLM calls", metrics.get("llm_resume_extraction_calls", 0))
    readiness_cols[2].metric("Recovery called", _yes_no(llm_recovery.get("called", False)))
    readiness_cols[3].metric(
        "Approval file",
        "ready" if approvals_result is not None and approvals_result.ok else "check",
    )

    if approvals_result is not None and not approvals_result.ok:
        st.warning(approvals_result.errors[0])

    _render_optional_feature_status(metrics)


def _render_all_runs_dashboard() -> None:
    run_dirs = _run_directories(RUNS_ROOT)
    if not run_dirs:
        st.info("No generated runs found yet.")
        return

    run_states = [_load_run_state(run_dir) for run_dir in run_dirs]
    summary = build_dashboard_summary(run_states)

    cols = st.columns(5)
    cols[0].metric("Runs", summary["run_count"])
    cols[1].metric("Candidates", summary["candidate_count"])
    cols[2].metric("Decisions", summary["decision_count"])
    cols[3].metric("Findings", summary["finding_count"])
    cols[4].metric("Approved", summary["approved_count"])

    st.markdown("#### Runs")
    st.dataframe(
        pd.DataFrame(summary["run_rows"]),
        use_container_width=True,
        hide_index=True,
        column_order=[
            "run_id",
            "bundle_id",
            "scenario_type",
            "candidate_count",
            "decision_count",
            "finding_count",
            "approved_count",
            "status",
        ],
    )

    st.markdown("#### Routing Across Runs")
    if summary["routing_rows"]:
        st.dataframe(
            pd.DataFrame(summary["routing_rows"]),
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("Routing metrics are not available across generated runs.")

    _render_optional_feature_status(summary["metrics"])


def _render_candidate_review(run_state: dict[str, Any]) -> None:
    if run_state["run_dir"] is None:
        st.info("No run selected yet.")
        return

    rows = run_state["candidate_rows"]
    if not rows:
        st.info("No candidate routing rows are available for this run.")
        return

    st.subheader("Candidate Review")
    routing_filter = st.multiselect(
        "Routing category",
        options=sorted({row["routing_category"] for row in rows}),
        default=sorted({row["routing_category"] for row in rows}),
    )
    approval_filter = st.multiselect(
        "Approval status",
        options=sorted({row["approval_label"] for row in rows}),
        default=sorted({row["approval_label"] for row in rows}),
    )

    filtered_rows = [
        row
        for row in rows
        if row["routing_category"] in routing_filter
        and row["approval_label"] in approval_filter
    ]
    if not filtered_rows:
        st.info("No candidates match the selected filters.")
        return

    st.dataframe(
        pd.DataFrame(filtered_rows),
        use_container_width=True,
        hide_index=True,
        column_order=[
            "candidate_name",
            "candidate_id",
            "routing_category",
            "score",
            "approval_label",
            "finding_count",
            "blocking_finding_count",
            "requires_human_approval",
        ],
    )

    selected_key = st.selectbox(
        "Candidate detail",
        options=[_candidate_key(row) for row in filtered_rows],
    )
    selected_row = next(row for row in filtered_rows if _candidate_key(row) == selected_key)
    _render_candidate_detail(run_state, selected_row)


def _render_candidate_detail(
    run_state: dict[str, Any],
    row: dict[str, Any],
    *,
    show_approval_hint: bool = True,
) -> None:
    payloads = run_state["payloads"]
    profile = _profile_lookup(read_candidate_profiles_payload(payloads)).get(
        (row["candidate_id"], row["application_id"])
    )
    match = _match_lookup(payloads.get("match_scores")).get(row["application_id"])
    findings = _candidate_findings(
        payloads.get("final_decision"),
        candidate_id=row["candidate_id"],
        application_id=row["application_id"],
    )

    st.markdown("#### Candidate Detail")
    cols = st.columns([1.1, 1.1, 1.4])
    cols[0].metric("Recommendation", row["routing_category"])
    cols[1].metric("Score", row["score"] if row["score"] is not None else "n/a")
    cols[2].metric("Approval", row["approval_label"])

    st.markdown(f"**Reason:** {row['reason']}")

    if profile:
        _render_profile_summary(profile)
    else:
        st.info("Candidate profile artifact is not available for this candidate.")

    if match:
        _render_match_summary(match)

    _render_finding_summary(findings)
    if show_approval_hint:
        st.info("Use the Approvals tab to save or update the human review decision.")


def _render_approvals(run_state: dict[str, Any], *, reviewer_name: str) -> None:
    if run_state["run_dir"] is None:
        st.info("No run selected yet.")
        return

    rows = run_state["candidate_rows"]
    if not rows:
        st.info("No candidates are available for approval.")
        return

    st.subheader("Approvals")
    st.caption("Approvals are local decision-support records, not final hiring actions.")

    selected_key = st.selectbox(
        "Candidate",
        options=[_candidate_key(row) for row in rows],
        key="approval_candidate_select",
    )
    row = next(item for item in rows if _candidate_key(item) == selected_key)
    _render_candidate_detail(run_state, row, show_approval_hint=False)
    _render_approval_form(
        run_state,
        row,
        reviewer_name=reviewer_name,
        form_namespace="approvals",
    )

    approvals = [
        row
        for row in rows
        if row["approval_action"] in APPROVAL_OPTIONS.values()
    ]
    st.markdown("#### Recorded Decisions")
    if approvals:
        st.dataframe(pd.DataFrame(approvals), use_container_width=True, hide_index=True)
    else:
        st.info("No reviewer decisions have been recorded yet.")


def _render_approval_form(
    run_state: dict[str, Any],
    row: dict[str, Any],
    *,
    reviewer_name: str,
    form_namespace: str,
) -> None:
    run_dir = run_state["run_dir"]
    if run_dir is None:
        return

    st.markdown("#### Human Approval")
    with st.form(
        f"{form_namespace}_approval_{row['candidate_id']}_{row['application_id']}"
    ):
        action_label = st.radio(
            "Decision",
            options=list(APPROVAL_OPTIONS),
            horizontal=True,
        )
        note = st.text_area("Reviewer note", value=row.get("approval_note", ""))
        reviewed = st.checkbox(
            "I reviewed the candidate profile, match summary, findings, and routing rationale.",
        )
        submitted = st.form_submit_button("Save review decision", type="primary")

    if submitted:
        if not reviewer_name.strip():
            st.error("Enter a reviewer name in the sidebar before saving.")
            return
        if not reviewed:
            st.error("Confirm that you reviewed the candidate context before saving.")
            return
        try:
            upsert_reviewer_approval(
                run_dir=run_dir,
                candidate_id=row["candidate_id"],
                application_id=row["application_id"],
                action=APPROVAL_OPTIONS[action_label],
                reviewer_name=reviewer_name.strip(),
                note=note.strip(),
                source_routing_category=row["routing_category"],
                score=row["score"],
            )
        except ValueError as exc:
            st.error(str(exc))
        else:
            st.success("Reviewer decision saved.")
            st.rerun()


def _render_calendar_queue(run_state: dict[str, Any]) -> None:
    if run_state["run_dir"] is None:
        st.info("No run selected yet.")
        return

    st.subheader("Interview Scheduling")
    st.caption(
        "Find human-reviewable interview slots for approved candidates using "
        "Google Calendar availability. No events or invitations are created."
    )
    _render_schedule_generation_notice()

    schedule_payload = run_state["payloads"].get("interview_schedule")
    queue_rows = build_calendar_queue_rows(run_state["candidate_rows"])
    items = _schedule_items(schedule_payload)

    _render_scheduling_progress(
        approved_count=len(queue_rows),
        suggested_count=len(items),
    )
    _render_schedule_warnings(schedule_payload)

    if items:
        st.markdown("#### Proposed Interview Slots")
        _render_schedule_suggestions(
            run_state=run_state,
            items=items,
        )
        _render_schedule_generation_button(
            run_state["run_dir"],
            label="Refresh available slots",
            help_text="Re-check panel availability and rebuild the proposed slots.",
        )
        return

    if not queue_rows:
        st.info(
            "No candidates are ready for scheduling yet. Use the Approvals tab "
            "to approve a reviewed candidate for scheduling first."
        )
        return

    st.markdown("#### Ready For Scheduling")
    st.caption(
        "These candidates have been approved by a reviewer. The next step is to "
        "find an available panel time for human confirmation."
    )
    st.dataframe(
        pd.DataFrame(_calendar_queue_display_rows(queue_rows)),
        use_container_width=True,
        hide_index=True,
    )

    _render_schedule_generation_button(
        run_state["run_dir"],
        label="Find available slots",
        help_text="Look for open time on the selected panel calendar.",
    )


def _render_schedule_suggestions(
    *,
    run_state: dict[str, Any],
    items: list[dict[str, Any]],
) -> None:
    candidate_by_key = {
        (row.get("candidate_id"), row.get("application_id")): row
        for row in run_state["candidate_rows"]
    }

    rows = []
    for item in items:
        key = (item.get("candidate_id"), item.get("application_id"))
        candidate = candidate_by_key.get(key, {})
        rows.append(
            {
                "candidate": candidate.get("candidate_name")
                or item.get("candidate_id"),
                "proposed_time": _format_kosovo_time(item.get("suggested_time")),
                "duration": f"{item.get('duration_minutes')} min",
                "panel": _format_panel_members(item),
                "status": "Needs human confirmation",
            }
        )

    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    st.caption(
        "Review the proposed time with the candidate and panel before creating "
        "an event manually in Google Calendar."
    )

    for item in items:
        key = (item.get("candidate_id"), item.get("application_id"))
        candidate = candidate_by_key.get(key, {})
        label = candidate.get("candidate_name") or item.get("candidate_id")
        st.divider()
        st.markdown(f"**{label}**")
        detail_cols = st.columns([1.4, 1, 1])
        detail_cols[0].metric(
            "Proposed time",
            _format_kosovo_time(item.get("suggested_time")),
        )
        detail_cols[1].metric("Duration", f"{item.get('duration_minutes')} min")
        detail_cols[2].metric("Status", "Needs confirmation")
        st.caption(f"Panel: {_format_panel_members(item)}")


def _render_scheduling_progress(
    *,
    approved_count: int,
    suggested_count: int,
) -> None:
    cols = st.columns(2)
    cols[0].metric("Ready", approved_count)
    cols[1].metric("Proposed slots", suggested_count)

    if suggested_count:
        st.info("A slot is proposed and waiting for human confirmation.")
    elif approved_count:
        st.info("Approved candidates are ready. Find available slots to continue.")
    else:
        st.info("Start by approving a reviewed candidate for scheduling.")


def _render_schedule_warnings(payload: Any) -> None:
    if not isinstance(payload, dict):
        return
    warnings = [
        warning
        for warning in payload.get("warnings") or []
        if isinstance(warning, dict) and warning.get("message")
    ]
    if not warnings:
        return
    with st.expander("Scheduling notes", expanded=False):
        for warning in warnings:
            st.warning(str(warning["message"]))


def _calendar_queue_display_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate": row.get("candidate_name"),
            "status": "Ready for scheduling",
            "approved_by": row.get("reviewer_name"),
            "approved_at": row.get("approval_updated_at"),
        }
        for row in rows
    ]


def _schedule_items(payload: Any) -> list[dict[str, Any]]:
    if not schedule_payload_has_items(payload):
        return []
    return [item for item in payload.get("items") or [] if isinstance(item, dict)]


def _format_panel_members(item: dict[str, Any]) -> str:
    members = item.get("panel_members") or []
    names = [
        str(member.get("name") or member.get("email") or member.get("calendar_id"))
        for member in members
        if isinstance(member, dict)
        and (member.get("name") or member.get("email") or member.get("calendar_id"))
    ]
    return ", ".join(names) if names else "To be confirmed"


def _format_kosovo_time(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    try:
        scheduled_at = datetime.fromisoformat(value).astimezone(KOSOVO_TIMEZONE)
    except ValueError:
        return value

    date_text = scheduled_at.strftime("%a, %b %d, %Y")
    date_text = date_text.replace(" 0", " ")
    return f"{date_text}, {scheduled_at:%H:%M} Kosovo time"


def _render_schedule_generation_button(
    run_dir: Path,
    *,
    label: str,
    help_text: str,
) -> None:
    if st.button(label, type="primary", help=help_text):
        try:
            stage = run_interview_schedule_stage(
                scaffold=_scaffold_from_run_dir(run_dir)
            )
        except Exception as exc:
            st.session_state[SCHEDULE_GENERATION_NOTICE_KEY] = {
                "kind": "error",
                "message": f"Could not generate schedule suggestions: {exc}",
            }
            st.rerun()
            return

        if stage.warnings:
            st.session_state[SCHEDULE_GENERATION_NOTICE_KEY] = {
                "kind": "warning",
                "message": stage.warnings[0],
            }
        else:
            st.session_state[SCHEDULE_GENERATION_NOTICE_KEY] = {
                "kind": "success",
                "message": "Available slot found. Review and confirm it manually.",
            }
        st.rerun()


def _render_schedule_generation_notice() -> None:
    notice = st.session_state.pop(SCHEDULE_GENERATION_NOTICE_KEY, None)
    if not isinstance(notice, dict):
        return

    message = notice.get("message")
    if not message:
        return

    kind = notice.get("kind")
    if kind == "error":
        st.error(message)
    elif kind == "warning":
        st.warning(message)
    else:
        st.success(message)


def _scaffold_from_run_dir(run_dir: Path) -> RunScaffold:
    return RunScaffold(
        run_id=run_dir.name,
        run_dir=run_dir,
        inputs_dir=run_dir / "inputs",
        artifacts_dir=run_dir / "artifacts",
        logs_dir=run_dir / "logs",
        tmp_dir=run_dir / "tmp",
    )


def _render_artifacts(run_state: dict[str, Any]) -> None:
    if run_state["run_dir"] is None:
        st.info("No run selected yet.")
        return

    catalog = run_state["catalog"]
    if catalog is None or not catalog.ok:
        st.error("Could not read artifact catalog.")
        for error in catalog.errors if catalog else ():
            st.warning(error)
        return

    display_artifacts = _display_artifacts(
        catalog.artifacts,
        display_artifact_keys=DISPLAY_ARTIFACT_KEYS,
    )
    if not display_artifacts:
        st.info("No displayable artifacts found in artifact_manifest.json.")
        return

    for artifact in display_artifacts:
        _render_artifact(artifact)


def _render_profile_summary(profile: dict[str, Any]) -> None:
    st.markdown("#### Profile")
    full_name = profile.get("full_name") or {}
    contact = [
        ("Name", full_name.get("value")),
        ("Email", (profile.get("email") or {}).get("value")),
        ("Phone", (profile.get("phone") or {}).get("value")),
        ("Location", (profile.get("location") or {}).get("value")),
    ]
    st.dataframe(
        pd.DataFrame(
            [{"Field": label, "Value": value or "not available"} for label, value in contact]
        ),
        use_container_width=True,
        hide_index=True,
    )

    skills = profile.get("skills") or []
    if skills:
        st.markdown("**Skills**")
        st.write(", ".join(skill.get("name", "") for skill in skills[:18] if skill.get("name")))

    flags = profile.get("manual_review_flags") or []
    for flag in flags:
        st.warning(flag)


def _render_match_summary(match: dict[str, Any]) -> None:
    st.markdown("#### Match")
    st.metric("Match score", match.get("score"))
    checks = (match.get("must_have_results") or []) + (match.get("nice_to_have_results") or [])
    if checks:
        st.dataframe(
            pd.DataFrame(
                [
                    {
                        "Requirement": item.get("label"),
                        "Required": item.get("required"),
                        "Satisfied": item.get("satisfied"),
                        "Explanation": item.get("explanation"),
                    }
                    for item in checks
                ]
            ),
            use_container_width=True,
            hide_index=True,
        )


def _render_finding_summary(findings: list[dict[str, Any]]) -> None:
    st.markdown("#### Findings")
    if not findings:
        st.success("No candidate-specific findings were generated.")
        return

    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Severity": finding.get("severity"),
                    "Category": finding.get("category"),
                    "Title": finding.get("title"),
                    "Recommendation": finding.get("recommendation"),
                }
                for finding in findings
            ]
        ),
        use_container_width=True,
        hide_index=True,
    )

    with st.expander("Evidence snippets", expanded=False):
        for finding in findings:
            st.markdown(f"**{finding.get('title')}**")
            evidence_items = finding.get("evidence") or []
            evidence_lines = [
                line
                for evidence in evidence_items
                if isinstance(evidence, dict)
                for line in (_format_evidence_item(evidence),)
                if line
            ]
            if evidence_lines:
                for line in evidence_lines[:5]:
                    st.code(line)
            else:
                st.caption("No evidence reference available.")


def _format_evidence_item(evidence: dict[str, Any]) -> str | None:
    snippet = evidence.get("text_snippet")
    if snippet:
        return str(snippet)

    parts = []
    for label, key in (
        ("source", "source_type"),
        ("section", "section"),
        ("field", "field_path"),
        ("file", "source_path"),
        ("reason", "missing_reason"),
    ):
        value = evidence.get(key)
        if value:
            parts.append(f"{label}: {value}")

    return " | ".join(parts) if parts else None


def _render_optional_feature_status(metrics: dict[str, Any]) -> None:
    st.markdown("#### Future Feature Readiness")
    rows = [
        {
            "Area": "Interview scheduling",
            "Status": f"{metrics.get('interview_schedule_items_created', 0)} item(s)",
        },
        {
            "Area": "Fraud findings",
            "Status": f"{metrics.get('fraud_findings_count', 0)} finding(s)",
        },
        {
            "Area": "ATS mock records",
            "Status": f"{metrics.get('ats_mock_records_loaded', 0)} loaded",
        },
        {
            "Area": "Scanned resumes",
            "Status": f"{metrics.get('scanned_resume_detected_count', 0)} detected",
        },
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def _render_artifact(artifact: ArtifactCatalogItem) -> None:
    label = artifact.filename
    artifact_kind = _artifact_kind(artifact.relative_path)

    with st.expander(label, expanded=False):
        st.caption(
            f"`{artifact.relative_path.as_posix()}` | "
            f"Owner: {artifact.owner} | "
            f"Required: {_yes_no(artifact.required_for_mvp)} | "
            f"Status: {artifact.status}"
        )

        st.write(artifact.description)

        if not artifact.is_available:
            st.info("not generated yet")
            return

        if artifact_kind == "json":
            _render_json(artifact.absolute_path)
        elif artifact_kind == "csv":
            _render_csv(artifact.absolute_path)
        elif artifact_kind == "markdown":
            _render_markdown(artifact.absolute_path)
        else:
            _render_text(artifact.absolute_path)


if __name__ == "__main__":
    main()
