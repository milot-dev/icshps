from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import pandas as pd
import streamlit as st

ArtifactKind = Literal["json", "markdown", "csv"]

RUNS_ROOT = Path("runs")

ARTIFACTS: tuple[tuple[str, Path, ArtifactKind], ...] = (
    ("context_packet.json", Path("inputs/context_packet.json"), "json"),
    ("intake_findings.json", Path("artifacts/intake_findings.json"), "json"),
    ("candidate_profile.json", Path("artifacts/candidate_profile.json"), "json"),
    ("match_scores.json", Path("artifacts/match_scores.json"), "json"),
    ("compliance_flags.md", Path("artifacts/compliance_flags.md"), "markdown"),
    ("verification_findings.json", Path("artifacts/verification_findings.json"), "json"),
    ("anomaly_findings.json", Path("artifacts/anomaly_findings.json"), "json"),
    ("final_decision.json", Path("artifacts/final_decision.json"), "json"),
    ("shortlist.csv", Path("artifacts/shortlist.csv"), "csv"),
    ("hiring_packet.json", Path("artifacts/hiring_packet.json"), "json"),
    ("metrics.json", Path("artifacts/metrics.json"), "json"),
    ("audit_log.md", Path("artifacts/audit_log.md"), "markdown"),
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

    for label, relative_path, artifact_kind in ARTIFACTS:
        _render_artifact(
            label=label,
            path=selected_run / relative_path,
            artifact_kind=artifact_kind,
        )


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


def _render_artifact(*, label: str, path: Path, artifact_kind: ArtifactKind) -> None:
    with st.expander(label, expanded=False):
        st.caption(str(path))

        if not path.exists():
            st.info("not generated yet")
            return

        if artifact_kind == "json":
            _render_json(path)
        elif artifact_kind == "csv":
            _render_csv(path)
        else:
            _render_markdown(path)


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


if __name__ == "__main__":
    main()
