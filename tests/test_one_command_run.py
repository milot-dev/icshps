from __future__ import annotations

import subprocess
import sys
from pathlib import Path


FINAL_ARTIFACTS = (
    Path("artifacts/final_decision.json"),
    Path("artifacts/shortlist.csv"),
    Path("artifacts/hiring_packet.json"),
    Path("artifacts/metrics.json"),
    Path("artifacts/audit_log.md"),
)


def test_one_command_run_generates_final_artifacts(tmp_path: Path) -> None:
    bundle_path = Path("data/hiring_bundles/clean_standard_application")
    runs_root = tmp_path / "runs"
    run_id = "pytest_clean_standard"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_pipeline.py",
            str(bundle_path),
            "--runs-root",
            str(runs_root),
            "--run-id",
            run_id,
            "--reset",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ICSHPS pipeline completed." in result.stdout
    assert f"Run ID: {run_id}" in result.stdout

    run_dir = runs_root / run_id
    assert run_dir.exists()

    for artifact_path in FINAL_ARTIFACTS:
        assert (run_dir / artifact_path).exists(), artifact_path


def test_one_command_run_fails_for_invalid_bundle(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_pipeline.py",
            str(tmp_path / "missing_bundle"),
            "--runs-root",
            str(tmp_path / "runs"),
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "ICSHPS pipeline failed:" in result.stderr
    assert "does not exist" in result.stderr


def test_one_command_run_accepts_single_pdf_resume(tmp_path: Path) -> None:
    resume_path = Path(
        "data/hiring_bundles/clean_standard_application/resumes/"
        "candidate_clean_001_resume.pdf"
    )
    runs_root = tmp_path / "runs"
    run_id = "pytest_single_pdf"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_pipeline.py",
            str(resume_path),
            "--runs-root",
            str(runs_root),
            "--run-id",
            run_id,
            "--reset",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    run_dir = runs_root / run_id
    assert run_dir.exists()

    for artifact_path in FINAL_ARTIFACTS:
        assert (run_dir / artifact_path).exists(), artifact_path


def test_repeated_run_with_same_run_id_is_deterministic(tmp_path: Path) -> None:
    bundle_path = Path("data/hiring_bundles/clean_standard_application")
    runs_root = tmp_path / "runs"
    run_id = "pytest_deterministic"

    command = [
        sys.executable,
        "scripts/run_pipeline.py",
        str(bundle_path),
        "--runs-root",
        str(runs_root),
        "--run-id",
        run_id,
        "--reset",
    ]

    first = subprocess.run(command, text=True, capture_output=True, check=False)
    assert first.returncode == 0, first.stderr

    run_dir = runs_root / run_id
    first_outputs = {
        artifact: (run_dir / artifact).read_bytes()
        for artifact in FINAL_ARTIFACTS
    }

    second = subprocess.run(command, text=True, capture_output=True, check=False)
    assert second.returncode == 0, second.stderr

    second_outputs = {
        artifact: (run_dir / artifact).read_bytes()
        for artifact in FINAL_ARTIFACTS
    }

    assert first_outputs == second_outputs


def test_one_command_run_does_not_require_streamlit() -> None:
    script_text = Path("scripts/run_pipeline.py").read_text(encoding="utf-8")

    assert "streamlit" not in script_text.lower()
