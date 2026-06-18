from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pandas as pd
import streamlit as st

from icshps.services.artifact_catalog import ArtifactCatalogItem, read_artifact_catalog

ArtifactKind = Literal["json", "markdown", "csv", "text"]

RUNS_ROOT = Path("runs")

DISPLAY_ARTIFACT_KEYS: tuple[str, ...] = (
    "context_packet",
    "intake_findings",
    "candidate_profile",
    "match_scores",
    "compliance_flags",
    "verification_findings",
    "anomaly_findings",
    "final_decision",
    "shortlist",
    "hiring_packet",
    "metrics",
    "audit_log",
)


def main() -> None:
    st.set_page_config(page_title="ICSHPS Demo", layout="wide")

    st.title("ICSHPS - Intelligent Candidate Screening & Hiring Pipeline System")
    st.caption("Read-only final demo viewer for generated run artifacts.")

    selected_run = _select_run_directory(RUNS_ROOT)
    if selected_run is None:
        st.info("No run folders found yet.")
        return

    st.subheader("Run Artifacts")
    st.caption(f"Selected run: `{selected_run.name}`")

    catalog = read_artifact_catalog(selected_run)

    if not catalog.ok:
        st.error("Could not read artifact catalog.")
        for error in catalog.errors:
            st.warning(error)
        return

    display_artifacts = _display_artifacts(catalog.artifacts)

    if not display_artifacts:
        st.info("No displayable artifacts found in artifact_manifest.json.")
        return

    for artifact in display_artifacts:
        _render_artifact(artifact)


def _select_run_directory(runs_root: Path) -> Path | None:
    run_dirs = _run_directories(runs_root)
    if not run_dirs:
        return None

    selected_name = st.selectbox(
        "Run",
        options=[run_dir.name for run_dir in run_dirs],
        index=0,
    )

    return next(run_dir for run_dir in run_dirs if run_dir.name == selected_name)


def _run_directories(runs_root: Path) -> list[Path]:
    if not runs_root.exists():
        return []

    return sorted(
        [path for path in runs_root.iterdir() if path.is_dir()],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def _display_artifacts(
    artifacts: tuple[ArtifactCatalogItem, ...],
) -> list[ArtifactCatalogItem]:
    artifact_by_key = {artifact.key: artifact for artifact in artifacts}

    return [
        artifact_by_key[key]
        for key in DISPLAY_ARTIFACT_KEYS
        if key in artifact_by_key
    ]


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


def _artifact_kind(path: Path) -> ArtifactKind:
    suffix = path.suffix.lower()

    if suffix == ".json":
        return "json"

    if suffix == ".csv":
        return "csv"

    if suffix in {".md", ".markdown"}:
        return "markdown"

    return "text"


def _render_json(path: Path) -> None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        st.code(path.read_text(encoding="utf-8"), language="json")
        return

    st.json(payload)


def _render_csv(path: Path) -> None:
    try:
        dataframe = pd.read_csv(path)
    except (pd.errors.EmptyDataError, pd.errors.ParserError, UnicodeDecodeError):
        st.code(path.read_text(encoding="utf-8"), language="csv")
        return

    st.dataframe(dataframe, use_container_width=True)


def _render_markdown(path: Path) -> None:
    st.markdown(path.read_text(encoding="utf-8"))


def _render_text(path: Path) -> None:
    st.code(path.read_text(encoding="utf-8"))


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


if __name__ == "__main__":
    main()