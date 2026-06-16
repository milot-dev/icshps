from __future__ import annotations

import json
from pathlib import Path

from icshps.services.scenario_validation import (
    discover_scenario_bundles,
    validate_all_scenario_bundles,
    validate_final_decision,
    validate_required_artifacts,
    validate_scenario_bundle,
)

def test_validation_runner_detects_available_bundles() -> None:
    bundles = discover_scenario_bundles(Path("data/hiring_bundles"))

    assert Path("data/hiring_bundles/clean_standard_application") in bundles


def test_missing_scenarios_are_reported_clearly(tmp_path: Path) -> None:
    bundles_root = tmp_path / "hiring_bundles"
    bundles_root.mkdir()

    report = validate_all_scenario_bundles(
        bundles_root=bundles_root,
        runs_root=tmp_path / "runs",
        check_determinism=False,
    )

    assert not report.ok
    assert "clean_standard_application" in report.missing_scenarios
    assert report.results == ()


def test_missing_artifacts_are_reported_clearly(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "partial_run"
    (run_dir / "artifacts").mkdir(parents=True)
    (run_dir / "artifact_manifest.json").write_text("{}\n", encoding="utf-8")

    issues = validate_required_artifacts(run_dir)

    messages = [issue.message for issue in issues]
    assert any("inputs/context_packet.json" in message for message in messages)
    assert any("artifacts/final_decision.json" in message for message in messages)


def test_invalid_routing_is_reported_clearly(tmp_path: Path) -> None:
    final_decision_path = tmp_path / "final_decision.json"
    final_decision_path.write_text(
        json.dumps(
            {
                "run_id": "run_001",
                "bundle_id": "bundle_001",
                "scenario_type": "clean_standard_application",
                "decisions": [
                    {
                        "candidate_id": "candidate_001",
                        "application_id": "app_001",
                        "routing_category": "Manual review",
                        "reason": "Test mismatch.",
                        "score": 80.0,
                        "blocking_finding_ids": [],
                        "requires_human_approval": True,
                    }
                ],
                "findings": [],
                "summary": "Test artifact.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    issues, actual_routing = validate_final_decision(
        final_decision_path=final_decision_path,
        expected_routing="Fast-track review",
        scenario_type="clean_standard_application",
    )

    assert actual_routing == ("Manual review",)
    assert any(issue.check == "routing_matches_expected" for issue in issues)


def test_final_decisions_must_require_human_approval(tmp_path: Path) -> None:
    final_decision_path = tmp_path / "final_decision.json"
    final_decision_path.write_text(
        json.dumps(
            {
                "run_id": "run_001",
                "bundle_id": "bundle_001",
                "scenario_type": "clean_standard_application",
                "decisions": [
                    {
                        "candidate_id": "candidate_001",
                        "application_id": "app_001",
                        "routing_category": "Fast-track review",
                        "reason": "Test artifact.",
                        "score": 100.0,
                        "blocking_finding_ids": [],
                        "requires_human_approval": False,
                    }
                ],
                "findings": [],
                "summary": "Test artifact.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    issues, _ = validate_final_decision(
        final_decision_path=final_decision_path,
        expected_routing="Fast-track review",
        scenario_type="clean_standard_application",
    )

    assert any(issue.check == "human_approval_required" for issue in issues)


def test_deterministic_rerun_check_works_for_clean_bundle(tmp_path: Path) -> None:
    result = validate_scenario_bundle(
        bundle_path=Path("data/hiring_bundles/clean_standard_application"),
        runs_root=tmp_path / "runs",
        check_determinism=True,
    )

    assert result.passed, result.issues
    assert result.actual_routing == ("Fast-track review",)


def test_validation_does_not_require_streamlit_or_external_services() -> None:
    script_text = Path("scripts/validate_scenario_bundles.py").read_text(
        encoding="utf-8"
    ).lower()

    assert "streamlit" not in script_text
    assert "requests" not in script_text
    assert "httpx" not in script_text