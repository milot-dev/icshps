from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path
from typing import Any, Literal

import pandas as pd
import streamlit as st

from icshps.services.artifact_catalog import ArtifactCatalogItem
from icshps.services.reviewer_approvals import (
    ReviewerApproval,
    approval_action_label,
    approvals_by_application,
)
from icshps.utils.text import slugify

ArtifactKind = Literal["json", "markdown", "csv", "text"]


def build_candidate_review_rows(
    *,
    final_decision: Any,
    profiles: list[dict[str, Any]],
    match_results: Any,
    approvals: list[ReviewerApproval],
) -> list[dict[str, Any]]:
    if not isinstance(final_decision, dict):
        return []

    decisions = final_decision.get("decisions") or []
    findings = final_decision.get("findings") or []
    profile_by_key = profile_lookup(profiles)
    match_by_application = match_lookup(match_results)
    approval_by_key = approvals_by_application(approvals)

    rows: list[dict[str, Any]] = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue

        key = (decision.get("candidate_id"), decision.get("application_id"))
        profile = profile_by_key.get(key)
        approval = approval_by_key.get(key)
        candidate_findings = [
            finding
            for finding in findings
            if finding.get("candidate_id") == key[0]
            and finding.get("application_id") == key[1]
        ]
        match = match_by_application.get(decision.get("application_id"))

        rows.append(
            {
                "candidate_id": decision.get("candidate_id"),
                "application_id": decision.get("application_id"),
                "candidate_name": profile_name(profile),
                "routing_category": decision.get("routing_category"),
                "score": decision.get("score"),
                "match_score": match.get("score") if match else decision.get("score"),
                "requires_human_approval": decision.get(
                    "requires_human_approval",
                    True,
                ),
                "reason": decision.get("reason"),
                "blocking_finding_count": len(
                    decision.get("blocking_finding_ids") or []
                ),
                "finding_count": len(candidate_findings),
                "approval_action": approval.action if approval else None,
                "approval_label": approval_action_label(
                    approval.action if approval else None
                ),
                "approval_note": approval.note if approval else "",
                "reviewer_name": approval.reviewer_name if approval else "",
                "updated_at": approval.updated_at if approval else "",
            }
        )

    return sorted(
        rows,
        key=lambda row: (
            row["approval_label"] != "Not reviewed",
            -(row["score"] or -1),
            row["candidate_id"] or "",
        ),
    )


def build_calendar_queue_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "candidate_name": row["candidate_name"],
            "candidate_id": row["candidate_id"],
            "application_id": row["application_id"],
            "status": "Ready for scheduling",
            "source_routing_category": row["routing_category"],
            "score": row["score"],
            "reviewer_name": row["reviewer_name"],
            "approval_updated_at": row["updated_at"],
        }
        for row in rows
        if row["approval_action"] == "approve_for_scheduling"
    ]


def schedule_payload_has_items(payload: Any) -> bool:
    if not isinstance(payload, dict):
        return False
    items = payload.get("items")
    return isinstance(items, list) and bool(items)


def format_evidence_item(evidence: dict[str, Any]) -> str | None:
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


def build_dashboard_summary(run_states: list[dict[str, Any]]) -> dict[str, Any]:
    routing_counts: dict[str, int] = {}
    run_rows: list[dict[str, Any]] = []
    metric_totals = {
        "interview_schedule_items_created": 0,
        "fraud_findings_count": 0,
        "ats_mock_records_loaded": 0,
        "scanned_resume_detected_count": 0,
    }
    summary = {
        "run_count": 0,
        "candidate_count": 0,
        "decision_count": 0,
        "finding_count": 0,
        "approved_count": 0,
    }

    for state in run_states:
        payloads = state.get("payloads") or {}
        metrics = payloads.get("metrics") or {}
        final_decision = payloads.get("final_decision") or {}
        rows = state.get("candidate_rows") or []
        run_dir = state.get("run_dir")
        run_id = run_dir.name if isinstance(run_dir, Path) else metrics.get("run_id", "")
        approved_count = sum(
            1 for row in rows if row.get("approval_action") == "approve_for_scheduling"
        )
        decision_count = int(
            metrics.get("decision_count") or len(final_decision.get("decisions", []))
        )
        finding_count = int(
            metrics.get("finding_count") or len(final_decision.get("findings", []))
        )
        candidate_count = int(metrics.get("candidate_count") or len(rows))

        summary["run_count"] += 1
        summary["candidate_count"] += candidate_count
        summary["decision_count"] += decision_count
        summary["finding_count"] += finding_count
        summary["approved_count"] += approved_count

        for key in metric_totals:
            metric_totals[key] += int(metrics.get(key) or 0)

        for category, count in (
            metrics.get("routing_category_counts") or metrics.get("routing_counts") or {}
        ).items():
            routing_counts[category] = routing_counts.get(category, 0) + int(count)

        run_rows.append(
            {
                "run_id": run_id,
                "bundle_id": metrics.get("bundle_id")
                or final_decision.get("bundle_id", ""),
                "scenario_type": metrics.get("scenario_type")
                or final_decision.get("scenario_type", ""),
                "candidate_count": candidate_count,
                "decision_count": decision_count,
                "finding_count": finding_count,
                "approved_count": approved_count,
                "status": metrics.get("status", "available"),
            }
        )

    return {
        **summary,
        "metrics": metric_totals,
        "run_rows": sorted(run_rows, key=lambda row: row["run_id"]),
        "routing_rows": [
            {"Routing category": category, "Count": count}
            for category, count in sorted(routing_counts.items())
        ],
    }


def read_candidate_profiles_payload(payloads: dict[str, Any]) -> list[dict[str, Any]]:
    profiles = payloads.get("candidate_profiles")
    if isinstance(profiles, list):
        return [profile for profile in profiles if isinstance(profile, dict)]

    profile = payloads.get("candidate_profile")
    if isinstance(profile, dict):
        return [profile]

    return []


def extract_uploaded_bundle_zip(
    *,
    archive_bytes: bytes,
    filename: str,
    upload_root: Path,
) -> Path:
    """Extract one uploaded Hiring Bundle zip and return its bundle directory."""

    if not filename.lower().endswith(".zip"):
        raise ValueError("Uploaded bundle must be a .zip file.")

    bundle_slug = slugify(Path(filename).stem) or "uploaded_bundle"
    destination = upload_root / bundle_slug

    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)

    archive_path = destination / "_upload.zip"
    archive_path.write_bytes(archive_bytes)

    try:
        with zipfile.ZipFile(archive_path) as archive:
            _validate_zip_members(archive)
            archive.extractall(destination)
    except zipfile.BadZipFile as exc:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError("Uploaded bundle ZIP could not be read.") from exc
    except ValueError:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    finally:
        archive_path.unlink(missing_ok=True)

    bundle_path = _resolve_uploaded_bundle_root(destination)
    if bundle_path is None:
        shutil.rmtree(destination, ignore_errors=True)
        raise ValueError("Uploaded ZIP must contain exactly one manifest.yaml.")

    return bundle_path


def load_display_payloads(
    artifacts: tuple[ArtifactCatalogItem, ...],
    *,
    display_artifact_keys: tuple[str, ...],
) -> dict[str, Any]:
    payloads: dict[str, Any] = {}
    for artifact in artifacts:
        if artifact.key not in display_artifact_keys or not artifact.is_available:
            continue
        payloads[artifact.key] = read_artifact_payload(artifact)
    return payloads


def read_artifact_payload(artifact: ArtifactCatalogItem) -> Any:
    try:
        if artifact_kind(artifact.relative_path) == "json":
            return json.loads(artifact.absolute_path.read_text(encoding="utf-8"))
        if artifact_kind(artifact.relative_path) == "csv":
            return pd.read_csv(artifact.absolute_path).to_dict(orient="records")
        return artifact.absolute_path.read_text(encoding="utf-8")
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, pd.errors.ParserError):
        return None


def candidate_findings(
    final_decision: Any,
    *,
    candidate_id: str,
    application_id: str,
) -> list[dict[str, Any]]:
    if not isinstance(final_decision, dict):
        return []

    findings = final_decision.get("findings") or []
    return [
        finding
        for finding in findings
        if isinstance(finding, dict)
        and finding.get("candidate_id") == candidate_id
        and finding.get("application_id") == application_id
    ]


def profile_lookup(
    profiles: list[dict[str, Any]],
) -> dict[tuple[str | None, str | None], dict[str, Any]]:
    return {
        (profile.get("candidate_id"), profile.get("application_id")): profile
        for profile in profiles
    }


def match_lookup(match_results: Any) -> dict[str | None, dict[str, Any]]:
    if not isinstance(match_results, dict):
        return {}
    results = match_results.get("results") or []
    return {
        result.get("application_id"): result
        for result in results
        if isinstance(result, dict)
    }


def profile_name(profile: dict[str, Any] | None) -> str:
    if not profile:
        return "Unknown candidate"
    full_name = profile.get("full_name") or {}
    return full_name.get("value") or profile.get("candidate_id") or "Unknown candidate"


def candidate_key(row: dict[str, Any]) -> str:
    return f"{row['candidate_name']} | {row['candidate_id']} | {row['application_id']}"


def bundle_directories(bundles_root: Path) -> list[Path]:
    if not bundles_root.exists():
        return []

    return sorted(
        [
            path
            for path in bundles_root.iterdir()
            if path.is_dir() and (path / "manifest.yaml").exists()
        ],
        key=lambda path: path.name,
    )


def run_directories(runs_root: Path) -> list[Path]:
    if not runs_root.exists():
        return []

    return sorted(
        [
            path
            for path in runs_root.iterdir()
            if path.is_dir() and (path / "artifact_manifest.json").exists()
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def display_artifacts(
    artifacts: tuple[ArtifactCatalogItem, ...],
    *,
    display_artifact_keys: tuple[str, ...],
) -> list[ArtifactCatalogItem]:
    artifact_by_key = {artifact.key: artifact for artifact in artifacts}

    return [
        artifact_by_key[key]
        for key in display_artifact_keys
        if key in artifact_by_key
    ]


def artifact_kind(path: Path) -> ArtifactKind:
    suffix = path.suffix.lower()

    if suffix == ".json":
        return "json"

    if suffix == ".csv":
        return "csv"

    if suffix in {".md", ".markdown"}:
        return "markdown"

    return "text"


def yes_no(value: Any) -> str:
    return "yes" if bool(value) else "no"


def render_json(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.code(path.read_text(encoding="utf-8"), language="json")
        return

    st.json(payload)


def render_csv(path: Path) -> None:
    try:
        dataframe = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError):
        st.code(path.read_text(encoding="utf-8"), language="csv")
        return

    st.dataframe(dataframe, use_container_width=True)


def render_markdown(path: Path) -> None:
    st.markdown(path.read_text(encoding="utf-8"))


def render_text(path: Path) -> None:
    st.code(path.read_text(encoding="utf-8"))


def inject_styles() -> None:
    st.markdown(
        """
        <style>
        :root {
            --icshps-ink: #0f172a;
            --icshps-muted: #475569;
            --icshps-panel: #f8fafc;
            --icshps-border: #e2e8f0;
        }
        .block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
        [data-testid="stMetric"] {
            background: var(--icshps-panel);
            border: 1px solid var(--icshps-border);
            border-radius: 8px;
            padding: 0.75rem 0.9rem;
            color: var(--icshps-ink);
        }
        [data-testid="stMetric"] * {
            color: var(--icshps-ink) !important;
        }
        [data-testid="stMetricLabel"] * {
            color: var(--icshps-muted) !important;
        }
        div[data-testid="stDataFrame"],
        div[data-testid="stTable"] {
            color: var(--icshps-ink);
        }
        div[data-baseweb="select"] > div,
        div[data-testid="stTextInput"] input,
        div[data-testid="stTextArea"] textarea {
            background-color: #ffffff;
            color: var(--icshps-ink);
            -webkit-text-fill-color: var(--icshps-ink);
        }
        div[data-baseweb="select"] span,
        div[data-baseweb="select"] input,
        div[data-baseweb="tag"] span {
            color: var(--icshps-ink) !important;
            -webkit-text-fill-color: var(--icshps-ink);
        }
        div[data-baseweb="tag"] {
            background-color: #e0f2fe;
            border: 1px solid #bae6fd;
        }
        h1, h2, h3 {letter-spacing: 0;}
        div[data-testid="stAlert"] {border-radius: 8px;}
        </style>
        """,
        unsafe_allow_html=True,
    )


def _validate_zip_members(archive: zipfile.ZipFile) -> None:
    for member in archive.infolist():
        member_path = Path(member.filename)
        if member_path.is_absolute() or ".." in member_path.parts:
            raise ValueError("Uploaded ZIP contains an unsafe path.")


def _resolve_uploaded_bundle_root(destination: Path) -> Path | None:
    manifest_paths = [
        path
        for path in destination.rglob("manifest.yaml")
        if path.is_file() and "_upload.zip" not in path.parts
    ]

    if len(manifest_paths) != 1:
        return None

    return manifest_paths[0].parent
