from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from icshps.graph.langgraph_workflow import run_langgraph_workflow
from icshps.schemas import FinalDecisionArtifact, RunArtifactManifest


def test_langgraph_workflow_creates_current_backend_artifacts(
    tmp_path: Path,
) -> None:
    bundle_path = Path("data/hiring_bundles/clean_standard_application")

    result = run_langgraph_workflow(bundle_path, runs_root=tmp_path / "runs")

    assert result.status == "completed"
    assert result.ok
    assert result.run_dir is not None

    assert result.candidate_profile_path is not None
    assert result.candidate_profile_path.exists()

    assert result.match_scores_path is not None
    assert result.match_scores_path.exists()

    assert (result.run_dir / "artifacts" / "final_decision.json").exists()
    assert result.metrics_path is not None
    assert result.metrics_path.exists()
    assert result.audit_log_path is not None
    assert result.audit_log_path.exists()


def test_langgraph_workflow_outputs_validate_against_artifact_contracts(
    tmp_path: Path,
) -> None:
    bundle_path = Path("data/hiring_bundles/clean_standard_application")

    result = run_langgraph_workflow(bundle_path, runs_root=tmp_path / "runs")

    assert result.run_dir is not None
    assert result.artifact_manifest_path is not None

    final_decision = read_json(result.run_dir / "artifacts" / "final_decision.json")
    manifest = read_json(result.artifact_manifest_path)

    FinalDecisionArtifact.model_validate(final_decision)
    RunArtifactManifest.model_validate(manifest)


def test_langgraph_engine_flag_runs_pipeline(tmp_path: Path) -> None:
    bundle_path = Path("data/hiring_bundles/clean_standard_application")
    runs_root = tmp_path / "runs"
    run_id = "pytest_langgraph_engine"

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
            "--engine",
            "langgraph",
        ],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "ICSHPS pipeline completed." in result.stdout
    assert (runs_root / run_id / "artifacts" / "final_decision.json").exists()
    assert (runs_root / run_id / "artifacts" / "metrics.json").exists()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
